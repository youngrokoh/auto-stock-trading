from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

import anyio
import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    ListedShareCountRow,
    QuoteRow,
)
from auto_stock_trading.adapters.database.market_data_statements import instrument_id_for
from auto_stock_trading.adapters.database.market_data_stock_store import PostgresStockStore
from auto_stock_trading.adapters.database.reference_stock_rows import StockProfileRow
from auto_stock_trading.domain.market_data.listed_shares import ListedShareCount
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    InstrumentIdentityConflictError,
    ProductType,
    Quote,
    QuoteSnapshotObservation,
    RawBrokerResponse,
)
from auto_stock_trading.domain.market_data.stocks import StockMasterBundle, StockProfile
from auto_stock_trading.settings.runtime import Settings

_NOW: Final = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
# 실제 수집 데이터를 건드리지 않도록 테스트 전용 코드를 쓴다.
_SYMBOLS: Final = ("900010", "900020")


def _bundle(sectors: dict[str, tuple[str, str]], received_at: datetime) -> StockMasterBundle:
    profiles = tuple(
        StockProfile(
            symbol=symbol,
            isin=f"KR7{symbol}003",
            name=name,
            sector_code=sector,
            source="KIS_MASTER",
            received_at=received_at,
        )
        for symbol, (name, sector) in sectors.items()
    )
    return StockMasterBundle(
        profiles=profiles,
        raw=RawBrokerResponse(
            operation=BrokerOperation.STOCK_MASTER,
            endpoint="/fixture",
            request_fingerprint="stock_master:kospi",
            received_at=received_at,
            payload_json="{}",
        ),
        collected_at=received_at,
    )


def _snapshot(symbol: str, price: Decimal, received_at: datetime) -> QuoteSnapshotObservation:
    return QuoteSnapshotObservation(
        quote=Quote(
            symbol=symbol,
            price=price,
            open_price=price,
            high_price=price,
            low_price=price,
            previous_close=price,
            change=Decimal(0),
            change_percent=Decimal(0),
            volume=10,
            trading_value=Decimal(100),
            currency="KRW",
            source="KIS",
            as_of=received_at,
            received_at=received_at,
        ),
        listed_shares=ListedShareCount(
            symbol=symbol,
            share_count=5_969_782_550,
            source="KIS",
            as_of=received_at,
            received_at=received_at,
        ),
        raw=RawBrokerResponse(
            operation=BrokerOperation.QUOTE,
            endpoint="/fixture",
            request_fingerprint=f"quote:{symbol}",
            received_at=received_at,
            payload_json="{}",
        ),
    )


def test_stock_profiles_are_versioned_and_instrument_rows_keep_trading_status() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresStockStore.from_connection(connection)
            try:
                _ = await connection.execute(
                    delete(StockProfileRow).where(StockProfileRow.symbol.in_(_SYMBOLS))
                )
                _ = await connection.execute(
                    delete(InstrumentRow).where(InstrumentRow.symbol.in_(_SYMBOLS))
                )

                first = _bundle(
                    {"900010": ("테스트전자", "5"), "900020": ("테스트통신", "B")},
                    _NOW,
                )
                assert await store.save_master_bundle(first) == 2
                # 같은 값 재수집은 버전을 만들지 않는다.
                assert await store.save_master_bundle(first) == 0

                # 정기변경으로 업종이 바뀌면 이전 버전을 보존한 새 버전이다.
                reclassified = _bundle(
                    {"900010": ("테스트전자", "9"), "900020": ("테스트통신", "B")},
                    _NOW + timedelta(days=1),
                )
                assert await store.save_master_bundle(reclassified) == 1

                versions = (
                    await connection.execute(
                        select(StockProfileRow.version, StockProfileRow.superseded_at)
                        .where(StockProfileRow.symbol == "900010")
                        .order_by(StockProfileRow.version)
                    )
                ).all()
                assert [row[0] for row in versions] == [1, 2]
                assert versions[0][1] is not None

                assert await store.sector("900010") == "9"
                assert await store.sector("900020") == "B"
                assert await store.sector("069500") is None
                assert set(await store.universe_symbols()) >= {"900010", "900020"}

                # 마스터 수집이 종목 행을 만든다(모의환경 시세 응답에는 이름이 없다).
                created = (
                    await connection.execute(
                        select(
                            InstrumentRow.id,
                            InstrumentRow.name,
                            InstrumentRow.trading_status,
                        )
                        .where(InstrumentRow.symbol == "900010")
                        .where(InstrumentRow.product_type == "stock")
                    )
                ).all()
                assert [(row[1], row[2]) for row in created] == [("테스트전자", "active")]
                # 식별자는 번들 수집과 같은 결정적 값이어야 한다. 다르면 이후 시세·일봉
                # 저장이 존재하지 않는 종목 id를 참조해 외래키가 깨진다.
                assert created[0][0] == instrument_id_for(
                    country="KR",
                    exchange="XKRX",
                    symbol="900010",
                    product_type=ProductType.STOCK,
                    currency="KRW",
                )

                # 다른 경로가 알아낸 거래정지 상태를 마스터 재수집이 덮어쓰지 않는다.
                _ = await connection.execute(
                    update(InstrumentRow)
                    .where(InstrumentRow.symbol == "900010")
                    .values(trading_status="suspended")
                )
                assert await store.save_master_bundle(reclassified) == 0
                preserved = await connection.scalar(
                    select(InstrumentRow.trading_status).where(InstrumentRow.symbol == "900010")
                )
                assert preserved == "suspended"

                # 시세 스윕은 종목당 최신 한 행을 유지하고 상장주식수 사실을 함께 남긴다.
                await store.save_quote_snapshot(_snapshot("900010", Decimal(70_000), _NOW))
                await store.save_quote_snapshot(
                    _snapshot("900010", Decimal(71_000), _NOW + timedelta(minutes=1))
                )
                instrument_id = instrument_id_for(
                    country="KR",
                    exchange="XKRX",
                    symbol="900010",
                    product_type=ProductType.STOCK,
                    currency="KRW",
                )
                quotes = (
                    await connection.execute(
                        select(QuoteRow.price).where(QuoteRow.instrument_id == instrument_id)
                    )
                ).all()
                assert [row[0] for row in quotes] == [Decimal(71_000)]
                shares = await connection.scalar(
                    select(ListedShareCountRow.share_count).where(
                        ListedShareCountRow.instrument_id == instrument_id,
                        ListedShareCountRow.superseded_at.is_(None),
                    )
                )
                assert shares == 5_969_782_550
            finally:
                await store.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)


def test_the_master_refuses_a_symbol_already_stored_as_another_product_type() -> None:
    """마스터 수집도 같은 규칙을 쓴다. ETF로 저장된 코드를 주식으로 덮어쓰지 않는다."""

    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresStockStore.from_connection(connection)
            try:
                _ = await connection.execute(
                    delete(InstrumentRow).where(InstrumentRow.symbol == "900030")
                )
                _ = await connection.execute(
                    delete(StockProfileRow).where(StockProfileRow.symbol == "900030")
                )
                _ = await connection.execute(
                    insert(InstrumentRow).values(
                        id=instrument_id_for(
                            country="KR",
                            exchange="XKRX",
                            symbol="900030",
                            product_type=ProductType.ETF,
                            currency="KRW",
                        ),
                        country="KR",
                        exchange="XKRX",
                        symbol="900030",
                        product_type=ProductType.ETF.value,
                        currency="KRW",
                        name="테스트ETF",
                        trading_status="active",
                        source="KIS",
                        source_as_of=_NOW.date(),
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )

                bundle = _bundle({"900030": ("테스트전자", "5")}, _NOW)
                with pytest.raises(InstrumentIdentityConflictError):
                    _ = await store.save_master_bundle(bundle)

                rows = (
                    await connection.execute(
                        select(InstrumentRow.product_type).where(InstrumentRow.symbol == "900030")
                    )
                ).all()
                assert [row[0] for row in rows] == [ProductType.ETF.value]
                profiles = await connection.scalar(
                    select(func.count(StockProfileRow.id)).where(StockProfileRow.symbol == "900030")
                )
                assert profiles == 0
            finally:
                await store.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)
