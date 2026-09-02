"""ETF 추종 지수 버전 사실(ADR-0021 결정 3). PostgreSQL이 필요하다."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

import anyio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_data_etf_classification import (
    PostgresEtfClassificationSource,
    backfill_etf_index_classification,
)
from auto_stock_trading.adapters.database.market_data_etf_store import PostgresEtfStore
from auto_stock_trading.adapters.database.market_data_rows import EtfNavRow
from auto_stock_trading.adapters.database.reference_etf_rows import EtfIndexClassificationRow
from auto_stock_trading.domain.market_data.etf import EtfNavObservation, EtfNavSnapshot
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.settings.runtime import Settings

_UNIT: Final = Decimal("1.00")
_NOW: Final = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)
# 실제 수집 데이터를 건드리지 않도록 테스트 전용 코드를 쓴다.
_SYMBOL: Final = "900900"


def _observation(
    index_name: str,
    received_at: datetime,
    tracking_multiple: Decimal = _UNIT,
) -> EtfNavObservation:
    return EtfNavObservation(
        snapshot=EtfNavSnapshot(
            symbol=_SYMBOL,
            price=Decimal(10000),
            change_percent=Decimal("0.1"),
            volume=10,
            previous_volume=10,
            nav=Decimal(10001),
            divergence_rate=Decimal("-0.01"),
            tracking_error=Decimal("0.1"),
            tracking_multiple=tracking_multiple,
            net_asset_total=1000,
            listed_shares=100,
            manager="테스트자산운용",
            index_name=index_name,
            listing_date=None,
            currency="KRW",
            source="KIS",
            as_of=received_at,
            received_at=received_at,
        ),
        raw=RawBrokerResponse(
            operation=BrokerOperation.ETF_NAV,
            endpoint="/fixture",
            request_fingerprint=f"etf_nav:{_SYMBOL}:{received_at.isoformat()}",
            received_at=received_at,
            payload_json="{}",
        ),
    )


def test_index_classification_is_versioned_from_nav_observations() -> None:
    async def run() -> None:
        engine = create_async_engine(Settings().database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresEtfStore.from_connection(connection)
            source = PostgresEtfClassificationSource.from_connection(
                connection, clock=lambda: _NOW + timedelta(days=2)
            )
            try:
                _ = await connection.execute(
                    delete(EtfIndexClassificationRow).where(
                        EtfIndexClassificationRow.symbol == _SYMBOL
                    )
                )
                _ = await connection.execute(delete(EtfNavRow).where(EtfNavRow.symbol == _SYMBOL))

                await store.save_nav_observation(_observation("S&P 500", _NOW))
                # 같은 값 재관측은 버전을 만들지 않고 증거만 갱신한다.
                await store.save_nav_observation(_observation("S&P 500", _NOW + timedelta(days=1)))
                history = await source.history(_SYMBOL)
                assert [(h.version, h.superseded_at) for h in history] == [(1, None)]
                assert history[0].as_of == _NOW + timedelta(days=1)
                assert await source.sector(_SYMBOL) == "S&P 500"

                # 지수가 바뀌면 이전 버전을 보존한 새 버전이다.
                await store.save_nav_observation(
                    _observation("S&P 500 Total Return", _NOW + timedelta(days=2))
                )
                history = await source.history(_SYMBOL)
                assert [h.version for h in history] == [1, 2]
                assert history[0].superseded_at == _NOW + timedelta(days=2)
                assert history[1].superseded_at is None
                assert await source.sector(_SYMBOL) == "S&P 500 Total Return"

                # 추적배수가 바뀌어도 새 버전이고, 1이 아니면 미분류다.
                await store.save_nav_observation(
                    _observation("S&P 500 Total Return", _NOW + timedelta(days=3), Decimal("2.00"))
                )
                assert [h.version for h in await source.history(_SYMBOL)] == [1, 2, 3]
                assert await source.sector(_SYMBOL) is None
            finally:
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)


def test_a_stale_classification_reads_as_unclassified() -> None:
    async def run() -> None:
        engine = create_async_engine(Settings().database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresEtfStore.from_connection(connection)
            stale_clock = PostgresEtfClassificationSource.from_connection(
                connection, clock=lambda: _NOW + timedelta(days=31)
            )
            try:
                _ = await connection.execute(
                    delete(EtfIndexClassificationRow).where(
                        EtfIndexClassificationRow.symbol == _SYMBOL
                    )
                )
                _ = await connection.execute(delete(EtfNavRow).where(EtfNavRow.symbol == _SYMBOL))
                await store.save_nav_observation(_observation("KOSPI200", _NOW))

                assert (await stale_clock.current(_SYMBOL)) is not None  # 사실은 있다
                assert await stale_clock.sector(_SYMBOL) is None  # 그러나 오래되어 미분류다
            finally:
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)


def test_backfill_creates_facts_from_stored_snapshots_without_inventing_evidence() -> None:
    """사실 도입 전에 수집된 스냅샷은 갱신 경로를 지나지 않았다. 증거는 스냅샷의 것 그대로다."""

    async def run() -> None:
        engine = create_async_engine(Settings().database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresEtfStore.from_connection(connection)
            source = PostgresEtfClassificationSource.from_connection(
                connection, clock=lambda: _NOW + timedelta(days=1)
            )
            sessions = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            try:
                _ = await connection.execute(
                    delete(EtfIndexClassificationRow).where(
                        EtfIndexClassificationRow.symbol == _SYMBOL
                    )
                )
                _ = await connection.execute(delete(EtfNavRow).where(EtfNavRow.symbol == _SYMBOL))
                await store.save_nav_observation(_observation("NASDAQ 100", _NOW))
                # 사실 도입 전 상태를 재현한다: 스냅샷만 있고 사실은 없다.
                _ = await connection.execute(
                    delete(EtfIndexClassificationRow).where(
                        EtfIndexClassificationRow.symbol == _SYMBOL
                    )
                )
                assert await source.current(_SYMBOL) is None

                observed, created = await backfill_etf_index_classification(sessions)
                assert observed >= 1
                assert created >= 1
                fact = await source.current(_SYMBOL)
                assert fact is not None
                assert fact.index_name == "NASDAQ 100"
                assert fact.as_of == _NOW  # 스냅샷의 관측 시각 그대로, 지금이 아니다

                # 두 번 돌려도 새 버전은 없다.
                _, created_again = await backfill_etf_index_classification(sessions)
                assert created_again == 0
            finally:
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)
