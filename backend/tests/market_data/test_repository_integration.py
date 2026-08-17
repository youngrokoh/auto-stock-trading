from datetime import UTC, date, datetime

import anyio
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.brokers.kis_http import KisTransportError
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    MarketBarRow,
    QuoteRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.application.market_data import MarketDataCollector
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings
from tests.brokers.kis_fixture import create_fixture_adapter
from tests.market_data.db_cleanup import purge_instruments


def test_collection_recovers_and_upserts_normalized_market_data() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        adapter, _ = create_fixture_adapter()
        async with engine.connect() as connection:
            transaction = await connection.begin()
            repository = PostgresMarketDataRepository.from_connection(connection)
            collector = MarketDataCollector(adapter, repository)
            target = InstrumentTarget("005930", ProductType.STOCK)
            started_at = datetime(2026, 8, 14, 1, tzinfo=UTC)
            try:
                await purge_instruments(connection, (target.symbol,))
                _ = await connection.execute(
                    delete(RawApiResponseRow).where(
                        RawApiResponseRow.request_fingerprint.like(f"%:{target.symbol}%")
                    )
                )
                _ = await connection.execute(
                    delete(SyncStatusRow).where(SyncStatusRow.symbol == target.symbol)
                )
                await repository.mark_started(target, started_at)
                await repository.mark_failed(
                    target,
                    started_at,
                    KisTransportError.__name__,
                    "KIS request failed at fixture: network failure",
                )
                _ = await collector.collect(
                    target,
                    date(2026, 8, 12),
                    date(2026, 8, 13),
                    started_at,
                )
                _ = await collector.collect(
                    target,
                    date(2026, 8, 12),
                    date(2026, 8, 13),
                    started_at,
                )

                instrument_count = await connection.scalar(
                    select(func.count(InstrumentRow.id)).where(
                        InstrumentRow.symbol == target.symbol
                    )
                )
                quote_count = await connection.scalar(
                    select(func.count(QuoteRow.id))
                    .join(InstrumentRow, QuoteRow.instrument_id == InstrumentRow.id)
                    .where(InstrumentRow.symbol == target.symbol)
                )
                bar_count = await connection.scalar(
                    select(func.count(MarketBarRow.id))
                    .join(InstrumentRow, MarketBarRow.instrument_id == InstrumentRow.id)
                    .where(InstrumentRow.symbol == target.symbol)
                )
                raw_count = await connection.scalar(
                    select(func.count(RawApiResponseRow.id)).where(
                        RawApiResponseRow.request_fingerprint.like(f"%:{target.symbol}%")
                    )
                )
                sync_state = await connection.scalar(
                    select(SyncStatusRow.state).where(SyncStatusRow.symbol == target.symbol)
                )

                assert instrument_count == 1
                assert quote_count == 1
                assert bar_count == 2
                assert raw_count == 6
                assert sync_state == "success"
                stored_instrument = await repository.instrument(target.symbol)
                stored_quote = await repository.quote(target.symbol)
                assert stored_instrument is not None
                assert stored_quote is not None
                assert stored_instrument.source == "KIS"
                assert stored_quote.as_of.tzinfo is not None
                assert (
                    len(
                        await repository.daily_bars(
                            target.symbol,
                            date(2026, 8, 12),
                            date(2026, 8, 13),
                        )
                    )
                    == 2
                )
            finally:
                await adapter.close()
                await repository.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)


def test_kis_transport_error_does_not_include_credentials() -> None:
    error = KisTransportError("/uapi/example", 401)

    with pytest.raises(KisTransportError, match="HTTP 401"):
        raise error

    assert "app" not in str(error).lower()
    assert "secret" not in str(error).lower()
