from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anyio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_etf_reader import PostgresEtfReader
from auto_stock_trading.adapters.database.market_data_etf_store import PostgresEtfStore
from auto_stock_trading.adapters.database.market_data_rows import EtfNavRow, EtfProfileRow
from auto_stock_trading.domain.market_data.etf import (
    EtfMasterBundle,
    EtfNavObservation,
    EtfNavSnapshot,
    EtfProfile,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.settings.runtime import Settings

_NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
_SYMBOLS = ("069500", "0000H0")


def _raw(operation: BrokerOperation, fingerprint: str) -> RawBrokerResponse:
    return RawBrokerResponse(
        operation=operation,
        endpoint="/fixture",
        request_fingerprint=fingerprint,
        received_at=_NOW,
        payload_json="{}",
    )


def _bundle(names: dict[str, str], received_at: datetime) -> EtfMasterBundle:
    profiles = tuple(
        EtfProfile(
            symbol=symbol,
            isin=f"KR7{symbol.ljust(6, '0')}000"[:12],
            name=name,
            source="KIS_MASTER",
            received_at=received_at,
        )
        for symbol, name in names.items()
    )
    return EtfMasterBundle(
        profiles=profiles,
        raw=_raw(BrokerOperation.ETF_MASTER, "etf_master:kospi"),
        collected_at=received_at,
    )


def _snapshot(price: str, received_at: datetime) -> EtfNavSnapshot:
    return EtfNavSnapshot(
        symbol="069500",
        price=Decimal(price),
        change_percent=Decimal("0.00"),
        volume=495,
        previous_volume=17088038,
        nav=Decimal("110371.90"),
        divergence_rate=Decimal("-0.28"),
        tracking_error=Decimal("0.39"),
        tracking_multiple=Decimal("1.00"),
        net_asset_total=260643,
        listed_shares=236150000,
        manager="삼성자산운용(ETF)",
        index_name="KOSPI200",
        listing_date=None,
        currency="KRW",
        source="KIS",
        as_of=received_at,
        received_at=received_at,
    )


def test_etf_profiles_are_versioned_and_nav_snapshots_stay_latest_only() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresEtfStore.from_connection(connection)
            reader = PostgresEtfReader.from_connection(connection)
            try:
                _ = await connection.execute(
                    delete(EtfNavRow).where(EtfNavRow.symbol.in_(_SYMBOLS))
                )
                _ = await connection.execute(
                    delete(EtfProfileRow).where(EtfProfileRow.symbol.in_(_SYMBOLS))
                )

                first = _bundle({"069500": "KODEX 200", "0000H0": "KODEX 인도Nifty미드캡100"}, _NOW)
                assert await store.save_master_bundle(first) == 2
                assert await store.save_master_bundle(first) == 0

                renamed = _bundle(
                    {"069500": "KODEX 코스피200", "0000H0": "KODEX 인도Nifty미드캡100"},
                    _NOW + timedelta(days=1),
                )
                assert await store.save_master_bundle(renamed) == 1

                versions = (
                    await connection.execute(
                        select(EtfProfileRow.version, EtfProfileRow.superseded_at)
                        .where(EtfProfileRow.symbol == "069500")
                        .order_by(EtfProfileRow.version)
                    )
                ).all()
                assert [row[0] for row in versions] == [1, 2]
                assert versions[0][1] is not None

                observation = EtfNavObservation(
                    snapshot=_snapshot("110060", _NOW),
                    raw=_raw(BrokerOperation.ETF_NAV, "etf_nav:069500"),
                )
                await store.save_nav_observation(observation)
                refreshed = EtfNavObservation(
                    snapshot=replace(
                        _snapshot("111000", _NOW + timedelta(days=1)),
                        divergence_rate=Decimal("0.10"),
                    ),
                    raw=_raw(BrokerOperation.ETF_NAV, "etf_nav:069500"),
                )
                await store.save_nav_observation(refreshed)

                nav_count = await connection.scalar(
                    select(func.count(EtfNavRow.id)).where(EtfNavRow.symbol == "069500")
                )
                assert nav_count == 1

                listings = await reader.read_etf_list()
                by_symbol = {item.profile.symbol: item for item in listings}
                assert by_symbol["069500"].profile.name == "KODEX 코스피200"
                snapshot = by_symbol["069500"].snapshot
                assert snapshot is not None
                assert snapshot.price == Decimal(111000)
                assert snapshot.divergence_rate == Decimal("0.10")
                assert by_symbol["0000H0"].snapshot is None

                detail = await reader.read_etf("069500")
                assert detail is not None
                assert detail.profile.version == 2
                assert await reader.read_etf("999999") is None
            finally:
                await store.close()
                await reader.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)
