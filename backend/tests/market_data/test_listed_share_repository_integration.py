from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import anyio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    ListedShareCountRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings
from tests.brokers.kis_fixture import create_fixture_adapter
from tests.market_data.db_cleanup import purge_instruments

_TARGET = InstrumentTarget("005930", ProductType.STOCK)
_STARTED_AT = datetime(2026, 8, 14, 1, tzinfo=UTC)


def test_listed_share_counts_are_versioned_facts() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        adapter, _ = create_fixture_adapter()
        async with engine.connect() as connection:
            transaction = await connection.begin()
            repository = PostgresMarketDataRepository.from_connection(connection)
            try:
                await purge_instruments(connection, (_TARGET.symbol,))
                _ = await connection.execute(
                    delete(RawApiResponseRow).where(
                        RawApiResponseRow.request_fingerprint.like(f"%:{_TARGET.symbol}%")
                    )
                )
                _ = await connection.execute(
                    delete(SyncStatusRow).where(SyncStatusRow.symbol == _TARGET.symbol)
                )
                bundle = await adapter.fetch_bundle(_TARGET, date(2026, 8, 12), date(2026, 8, 13))

                await repository.save_bundle(bundle)
                await repository.save_bundle(bundle)

                first = await repository.listed_share_count(_TARGET.symbol)
                assert first is not None
                assert first.share_count == 5969782550
                assert first.version == 1
                assert first.superseded_at is None

                later = bundle.listed_shares.received_at + timedelta(hours=1)
                changed = replace(
                    bundle,
                    listed_shares=replace(
                        bundle.listed_shares,
                        share_count=5846278608,
                        as_of=later,
                        received_at=later,
                    ),
                )
                await repository.save_bundle(changed)

                current = await repository.listed_share_count(_TARGET.symbol)
                assert current is not None
                assert current.share_count == 5846278608
                assert current.version == 2
                assert current.superseded_at is None

                rows = (
                    await connection.execute(
                        select(
                            ListedShareCountRow.share_count,
                            ListedShareCountRow.version,
                            ListedShareCountRow.superseded_at,
                        )
                        .join(
                            InstrumentRow,
                            ListedShareCountRow.instrument_id == InstrumentRow.id,
                        )
                        .where(InstrumentRow.symbol == _TARGET.symbol)
                        .order_by(ListedShareCountRow.version)
                    )
                ).all()
                assert [(row[0], row[1]) for row in rows] == [
                    (5969782550, 1),
                    (5846278608, 2),
                ]
                assert rows[0][2] is not None
                assert rows[1][2] is None
            finally:
                await adapter.close()
                await repository.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)
