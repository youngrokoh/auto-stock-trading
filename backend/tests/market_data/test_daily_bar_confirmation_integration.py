from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, final

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow, MarketBarRow
from auto_stock_trading.application.market_data import DailyBarConfirmation, DailyBarConfirmer
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings
from tests.brokers.kis_fixture import create_fixture_adapter
from tests.market_data.db_cleanup import purge_instruments

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncConnection

    from auto_stock_trading.domain.market_data.models import MarketDataBundle

    type ConfirmationScenario = Callable[
        [PostgresMarketDataRepository, AsyncConnection, MarketDataBundle],
        Awaitable[None],
    ]

_TARGET = InstrumentTarget("005930", ProductType.STOCK)
_RANGE = (date(2026, 8, 12), date(2026, 8, 13))
# 15:40 Asia/Seoul == 06:40 UTC; both fixture bars closed before this instant on 2026-08-13.
_POST_CLOSE_FIRST = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
_CONFIRM_AT = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)
_SECOND_CONFIRM_AT = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)
_INTRADAY_FIRST = datetime(2026, 8, 12, 5, 0, tzinfo=UTC)


@final
class _QueuedSource:
    def __init__(self, bundles: list[MarketDataBundle]) -> None:
        self._bundles = bundles

    async def fetch_bundle(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
    ) -> MarketDataBundle:
        _ = (target, start_date, end_date)
        return self._bundles.pop(0)

    async def close(self) -> None:
        return None


def _observed(bundle: MarketDataBundle, received_at: datetime) -> MarketDataBundle:
    return replace(
        bundle,
        daily_bars=tuple(replace(bar, received_at=received_at) for bar in bundle.daily_bars),
        raw_responses=tuple(replace(raw, received_at=received_at) for raw in bundle.raw_responses),
        collected_at=received_at,
    )


def _corrected(bundle: MarketDataBundle, received_at: datetime) -> MarketDataBundle:
    observed = _observed(bundle, received_at)
    first, *remaining = observed.daily_bars
    return replace(
        observed,
        daily_bars=(replace(first, close_price=first.close_price + Decimal(1)), *remaining),
    )


async def _confirm(
    repository: PostgresMarketDataRepository,
    bundle: MarketDataBundle,
    now: datetime,
) -> DailyBarConfirmation:
    confirmer = DailyBarConfirmer(source=_QueuedSource([bundle]), store=repository)
    return await confirmer.confirm(_TARGET, _RANGE[0], _RANGE[1], now)


def test_matching_post_close_refetch_confirms_daily_bars() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        bundle: MarketDataBundle,
    ) -> None:
        # Given
        await repository.save_bundle(_observed(bundle, _POST_CLOSE_FIRST))

        # When
        result = await _confirm(repository, _observed(bundle, _CONFIRM_AT), _CONFIRM_AT)

        # Then
        rows = await _rows(connection)
        assert result.confirmed == 2
        assert result.pending == 0
        assert {row.finality for row in rows} == {"confirmed"}
        assert {row.confirmed_at for row in rows} == {_CONFIRM_AT}
        assert {row.version for row in rows} == {1}

    anyio.run(_run_scenario, scenario)


def test_intraday_first_observation_is_not_confirmation_evidence() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        bundle: MarketDataBundle,
    ) -> None:
        # Given
        await repository.save_bundle(_observed(bundle, _INTRADAY_FIRST))

        # When
        first = await _confirm(repository, _observed(bundle, _CONFIRM_AT), _CONFIRM_AT)
        second = await _confirm(
            repository,
            _observed(bundle, _SECOND_CONFIRM_AT),
            _SECOND_CONFIRM_AT,
        )

        # Then
        rows = await _rows(connection)
        assert first.confirmed == 0
        assert first.pending == 2
        assert second.confirmed == 2
        assert {row.finality for row in rows} == {"confirmed"}
        assert {row.version for row in rows} == {1}

    anyio.run(_run_scenario, scenario)


def test_differing_refetch_creates_pending_correction_instead_of_confirming() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        bundle: MarketDataBundle,
    ) -> None:
        # Given
        await repository.save_bundle(_observed(bundle, _POST_CLOSE_FIRST))

        # When
        result = await _confirm(repository, _corrected(bundle, _CONFIRM_AT), _CONFIRM_AT)

        # Then
        corrected_date = bundle.daily_bars[0].trading_date
        rows = await _rows(connection)
        corrected_rows = [row for row in rows if row.trading_date == corrected_date]
        assert result.confirmed == 1
        assert result.pending == 1
        assert tuple(row.version for row in corrected_rows) == (1, 2)
        assert corrected_rows[0].superseded_at is not None
        assert corrected_rows[1].finality == "pending"

    anyio.run(_run_scenario, scenario)


def test_same_day_bar_before_cutoff_stays_pending() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        bundle: MarketDataBundle,
    ) -> None:
        # Given: first observation after the 2026-08-12 close, before the 2026-08-13 close
        first_observed = datetime(2026, 8, 13, 4, 0, tzinfo=UTC)
        early_now = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
        await repository.save_bundle(_observed(bundle, first_observed))

        # When
        result = await _confirm(repository, _observed(bundle, early_now), early_now)

        # Then
        rows = {row.trading_date: row for row in await _rows(connection)}
        assert result.confirmed == 1
        assert result.pending == 1
        assert rows[date(2026, 8, 12)].finality == "confirmed"
        assert rows[date(2026, 8, 13)].finality == "pending"

    anyio.run(_run_scenario, scenario)


def test_confirmation_is_idempotent_and_keeps_first_confirmed_at() -> None:
    async def scenario(
        repository: PostgresMarketDataRepository,
        connection: AsyncConnection,
        bundle: MarketDataBundle,
    ) -> None:
        # Given
        await repository.save_bundle(_observed(bundle, _POST_CLOSE_FIRST))
        _ = await _confirm(repository, _observed(bundle, _CONFIRM_AT), _CONFIRM_AT)

        # When
        result = await _confirm(
            repository,
            _observed(bundle, _SECOND_CONFIRM_AT),
            _SECOND_CONFIRM_AT,
        )

        # Then
        rows = await _rows(connection)
        assert result.confirmed == 2
        assert result.pending == 0
        assert {row.confirmed_at for row in rows} == {_CONFIRM_AT}
        assert {row.version for row in rows} == {1}

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: ConfirmationScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    adapter, _ = create_fixture_adapter()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        repository = PostgresMarketDataRepository.from_connection(connection)
        try:
            await purge_instruments(connection, (_TARGET.symbol,))
            bundle = await adapter.fetch_bundle(_TARGET, _RANGE[0], _RANGE[1])
            await scenario(repository, connection, bundle)
        finally:
            await adapter.close()
            await repository.close()
            await transaction.rollback()
    await engine.dispose()


async def _rows(connection: AsyncConnection) -> tuple[MarketBarRow, ...]:
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
                    .where(InstrumentRow.symbol == _TARGET.symbol)
                    .order_by(MarketBarRow.trading_date, MarketBarRow.version)
                )
            ).all()
        )
