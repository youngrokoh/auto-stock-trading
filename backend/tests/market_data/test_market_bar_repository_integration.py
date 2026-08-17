from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow, MarketBarRow
from auto_stock_trading.domain.market_data.models import (
    InstrumentTarget,
    InvalidMarketBarError,
    ProductType,
)
from auto_stock_trading.settings.runtime import Settings
from tests.brokers.kis_fixture import create_fixture_adapter
from tests.market_data.db_cleanup import purge_instruments

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncConnection

    from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
    from auto_stock_trading.domain.market_data.models import MarketDataBundle

    type MarketBarScenario = Callable[
        [PostgresMarketDataRepository, AsyncConnection, KisMarketDataAdapter],
        Awaitable[None],
    ]


def test_identical_daily_bar_refresh_reuses_current_version() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        adapter: KisMarketDataAdapter,
    ) -> None:
        # Given
        bundle = await _initial_bundle(repository, connection, adapter)
        refreshed_at = bundle.daily_bars[0].received_at + timedelta(minutes=1)

        # When
        await repository.save_bundle(_refreshed_bundle(bundle, refreshed_at))

        # Then
        rows = await _rows(
            connection,
            bundle.daily_bars[0].symbol,
            bundle.daily_bars[0].trading_date,
        )
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].finality == "pending"
        assert rows[0].received_at == refreshed_at
        assert rows[0].superseded_at is None

    anyio.run(_run_scenario, scenario)


def test_daily_bar_confirmation_marks_matching_current_version() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        adapter: KisMarketDataAdapter,
    ) -> None:
        # Given
        bundle = await _initial_bundle(repository, connection, adapter)
        refreshed = _refreshed_bundle(
            bundle,
            bundle.daily_bars[0].received_at + timedelta(minutes=1),
        )
        await repository.save_bundle(refreshed)
        bar = refreshed.daily_bars[0]
        confirmed_at = bar.received_at + timedelta(minutes=1)

        # When
        confirmed = await repository.confirm_daily_bar(bar, confirmed_at)

        # Then
        rows = await _rows(connection, bar.symbol, bar.trading_date)
        assert confirmed
        assert len(rows) == 1
        assert rows[0].finality == "confirmed"
        assert rows[0].confirmed_at == confirmed_at

    anyio.run(_run_scenario, scenario)


def test_daily_bar_correction_supersedes_confirmed_version() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        adapter: KisMarketDataAdapter,
    ) -> None:
        # Given
        bundle = await _initial_bundle(repository, connection, adapter)
        refreshed = _refreshed_bundle(
            bundle,
            bundle.daily_bars[0].received_at + timedelta(minutes=1),
        )
        await repository.save_bundle(refreshed)
        bar = refreshed.daily_bars[0]
        confirmed_at = bar.received_at + timedelta(minutes=1)
        _confirmed = await repository.confirm_daily_bar(bar, confirmed_at)
        corrected_at = confirmed_at + timedelta(minutes=1)

        # When
        await repository.save_bundle(_corrected_bundle(refreshed, corrected_at))

        # Then
        rows = await _rows(connection, bar.symbol, bar.trading_date)
        current = await repository.daily_bars(
            bar.symbol,
            bar.trading_date,
            bar.trading_date,
        )
        assert tuple(row.version for row in rows) == (1, 2)
        assert rows[0].finality == "confirmed"
        assert rows[0].superseded_at == corrected_at
        assert rows[1].finality == "pending"
        assert rows[1].confirmed_at is None
        assert rows[1].superseded_at is None
        assert len(current) == 1
        assert current[0].version == 2
        assert current[0].bar.close_price == bar.close_price + Decimal(1)

    anyio.run(_run_scenario, scenario)


def test_stale_daily_bar_correction_does_not_create_history() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        adapter: KisMarketDataAdapter,
    ) -> None:
        # Given
        bundle = await _initial_bundle(repository, connection, adapter)
        refreshed_at = bundle.daily_bars[0].received_at + timedelta(minutes=2)
        await repository.save_bundle(_refreshed_bundle(bundle, refreshed_at))
        stale_correction_at = refreshed_at - timedelta(minutes=1)

        # When
        with pytest.raises(InvalidMarketBarError):
            await repository.save_bundle(_corrected_bundle(bundle, stale_correction_at))

        # Then
        bar = bundle.daily_bars[0]
        rows = await _rows(connection, bar.symbol, bar.trading_date)
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].received_at == refreshed_at
        assert rows[0].superseded_at is None

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: MarketBarScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    adapter, _ = create_fixture_adapter()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        repository = PostgresMarketDataRepository.from_connection(connection)
        try:
            await scenario(repository, connection, adapter)
        finally:
            await adapter.close()
            await repository.close()
            await transaction.rollback()
    await engine.dispose()


async def _initial_bundle(
    repository: PostgresMarketDataRepository,
    connection: AsyncConnection,
    adapter: KisMarketDataAdapter,
) -> MarketDataBundle:
    target = InstrumentTarget("005930", ProductType.STOCK)
    await purge_instruments(connection, (target.symbol,))
    bundle = await adapter.fetch_bundle(target, date(2026, 8, 12), date(2026, 8, 13))
    await repository.save_bundle(bundle)
    return bundle


def _refreshed_bundle(bundle: MarketDataBundle, received_at: datetime) -> MarketDataBundle:
    return replace(
        bundle,
        daily_bars=tuple(replace(bar, received_at=received_at) for bar in bundle.daily_bars),
        raw_responses=tuple(replace(raw, received_at=received_at) for raw in bundle.raw_responses),
        collected_at=received_at,
    )


def _corrected_bundle(bundle: MarketDataBundle, received_at: datetime) -> MarketDataBundle:
    refreshed = _refreshed_bundle(bundle, received_at)
    first, *remaining = refreshed.daily_bars
    corrected = replace(first, close_price=first.close_price + Decimal(1))
    return replace(refreshed, daily_bars=(corrected, *remaining))


async def _rows(
    connection: AsyncConnection,
    symbol: str,
    trading_date: date,
) -> tuple[MarketBarRow, ...]:
    async with AsyncSession(
        connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        return tuple(
            (
                await session.scalars(
                    select(MarketBarRow)
                    .join(InstrumentRow, MarketBarRow.instrument_id == InstrumentRow.id)
                    .where(
                        InstrumentRow.symbol == symbol,
                        MarketBarRow.trading_date == trading_date,
                    )
                    .order_by(MarketBarRow.version)
                )
            ).all()
        )
