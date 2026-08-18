from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.strategy_backtest_reader import (
    PostgresBacktestReader,
)
from auto_stock_trading.adapters.database.strategy_backtest_store import (
    PostgresBacktestStore,
)
from auto_stock_trading.domain.strategies.backtest import (
    BacktestMetrics,
    BacktestTrade,
    EquityPoint,
    TradeSkipReason,
)
from auto_stock_trading.domain.strategies.ma_rsi import SignalAction, SignalReason
from auto_stock_trading.domain.strategies.records import BacktestRunRecord
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    type StoreScenario = Callable[
        [PostgresBacktestStore, PostgresBacktestReader, AsyncConnection],
        Awaitable[None],
    ]

_NOW: Final = datetime(2026, 8, 18, 2, 0, tzinfo=UTC)
_SYMBOL: Final = "990001"


def _record(run_id: UUID, *, status: str = "completed") -> BacktestRunRecord:
    metrics = (
        BacktestMetrics(
            total_return_pct=Decimal("-5.10"),
            pre_cost_return_pct=Decimal("-4.68"),
            benchmark_return_pct=Decimal("-10.00"),
            excess_return_pct=Decimal("4.90"),
            mdd_pct=Decimal("-6.45"),
            sharpe=Decimal("-4.7476"),
            turnover_pct=Decimal("6210.57"),
            total_fee=Decimal(389),
            total_slippage=Decimal(1949),
            total_tax=Decimal(1903),
            trade_count=2,
        )
        if status == "completed"
        else None
    )
    return BacktestRunRecord(
        run_id=run_id,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"long_period":3,"rsi_overbought":"90","rsi_period":2,"short_period":2}',
        symbol=_SYMBOL,
        benchmark_symbol="069500",
        range_start=date(2026, 8, 3),
        range_end=date(2026, 8, 12),
        initial_cash=Decimal(1_000_000),
        signal_method="total_return",
        engine_version="backtest-1",
        cost_rule_versions='["research-krx-2026"]',
        input_bar_version_hash="c" * 64,
        action_version_hash="d" * 64,
        signal_dataset_id=uuid4(),
        benchmark_dataset_id=uuid4(),
        status=status,
        failure_code=None if status == "completed" else "missing_adjusted_dataset",
        metrics=metrics,
        created_at=_NOW,
    )


def _trades() -> tuple[BacktestTrade, ...]:
    return (
        BacktestTrade(
            sequence=1,
            signal_date=date(2026, 8, 7),
            execution_date=date(2026, 8, 10),
            action=SignalAction.BUY,
            reason=SignalReason.GOLDEN_CROSS,
            quantity=78,
            price=Decimal(12800),
            gross_amount=Decimal(998_400),
            fee=Decimal(199),
            slippage=Decimal(998),
            tax=Decimal(0),
            skip_reason=None,
        ),
        BacktestTrade(
            sequence=2,
            signal_date=date(2026, 8, 12),
            execution_date=None,
            action=SignalAction.SELL,
            reason=SignalReason.DEAD_CROSS,
            quantity=0,
            price=None,
            gross_amount=Decimal(0),
            fee=Decimal(0),
            slippage=Decimal(0),
            tax=Decimal(0),
            skip_reason=TradeSkipReason.WINDOW_END,
        ),
    )


def _equity() -> tuple[EquityPoint, ...]:
    return (
        EquityPoint(
            trading_date=date(2026, 8, 10),
            cash=Decimal(403),
            position_value=Decimal(1_014_000),
            nav=Decimal(1_014_403),
        ),
        EquityPoint(
            trading_date=date(2026, 8, 11),
            cash=Decimal(948_959),
            position_value=Decimal(0),
            nav=Decimal(948_959),
        ),
    )


def test_completed_run_round_trips_with_trades_and_equity() -> None:
    async def scenario(
        store: PostgresBacktestStore,
        reader: PostgresBacktestReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        record = _record(uuid4())

        await store.save_run(record, _trades(), _equity())

        runs = await reader.runs(10)
        assert record in runs
        loaded = await reader.run(record.run_id)
        assert loaded == record
        assert await reader.trades(record.run_id) == _trades()
        assert await reader.equity(record.run_id) == _equity()

    anyio.run(_run_scenario, scenario)


def test_failed_run_round_trips_without_results() -> None:
    async def scenario(
        store: PostgresBacktestStore,
        reader: PostgresBacktestReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        record = _record(uuid4(), status="failed")

        await store.save_run(record, (), ())

        loaded = await reader.run(record.run_id)
        assert loaded == record
        assert await reader.trades(record.run_id) == ()
        assert await reader.equity(record.run_id) == ()

    anyio.run(_run_scenario, scenario)


def test_saving_run_for_unknown_symbol_fails() -> None:
    async def scenario(
        store: PostgresBacktestStore,
        reader: PostgresBacktestReader,
        connection: AsyncConnection,
    ) -> None:
        _ = reader
        _ = connection
        record = replace(_record(uuid4()), symbol="999999")

        with pytest.raises(LookupError):
            await store.save_run(record, (), ())

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: StoreScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        store = PostgresBacktestStore.from_connection(connection)
        reader = PostgresBacktestReader.from_connection(connection)
        try:
            await scenario(store, reader, connection)
        finally:
            await store.close()
            await reader.close()
            await transaction.rollback()
    await engine.dispose()


async def _ensure_instrument(connection: AsyncConnection, symbol: str) -> UUID:
    existing = await connection.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == symbol).limit(1)
    )
    if existing is not None:
        return existing
    instrument_id = uuid4()
    _ = await connection.execute(
        insert(InstrumentRow).values(
            id=instrument_id,
            country="KR",
            exchange="KRX",
            symbol=symbol,
            product_type="stock",
            currency="KRW",
            name="백테스트 통합 테스트 종목",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="normal",
            source="TEST",
            source_as_of=date(2026, 8, 18),
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return instrument_id
