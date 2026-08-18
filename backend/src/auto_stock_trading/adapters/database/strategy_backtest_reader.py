from __future__ import annotations

from typing import TYPE_CHECKING, final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.strategy_backtest_rows import (
    BacktestEquityRow,
    BacktestRunRow,
    BacktestTradeRow,
)
from auto_stock_trading.domain.strategies.backtest import (
    BacktestMetrics,
    BacktestTrade,
    EquityPoint,
    TradeSkipReason,
)
from auto_stock_trading.domain.strategies.ma_rsi import SignalAction, SignalReason
from auto_stock_trading.domain.strategies.records import BacktestRunRecord

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


def _metrics_from(row: BacktestRunRow) -> BacktestMetrics | None:
    if (
        row.total_return_pct is None
        or row.pre_cost_return_pct is None
        or row.benchmark_return_pct is None
        or row.excess_return_pct is None
        or row.mdd_pct is None
        or row.turnover_pct is None
        or row.total_fee is None
        or row.total_slippage is None
        or row.total_tax is None
        or row.trade_count is None
    ):
        return None
    return BacktestMetrics(
        total_return_pct=row.total_return_pct,
        pre_cost_return_pct=row.pre_cost_return_pct,
        benchmark_return_pct=row.benchmark_return_pct,
        excess_return_pct=row.excess_return_pct,
        mdd_pct=row.mdd_pct,
        sharpe=row.sharpe,
        turnover_pct=row.turnover_pct,
        total_fee=row.total_fee,
        total_slippage=row.total_slippage,
        total_tax=row.total_tax,
        trade_count=row.trade_count,
    )


def _record_from(row: BacktestRunRow, symbol: str) -> BacktestRunRecord:
    return BacktestRunRecord(
        run_id=row.id,
        strategy_name=row.strategy_name,
        strategy_version=row.strategy_version,
        parameters_json=row.parameters_json,
        symbol=symbol,
        benchmark_symbol=row.benchmark_symbol,
        range_start=row.range_start,
        range_end=row.range_end,
        initial_cash=row.initial_cash,
        signal_method=row.signal_method,
        engine_version=row.engine_version,
        cost_rule_versions=row.cost_rule_versions,
        input_bar_version_hash=row.input_bar_version_hash,
        action_version_hash=row.action_version_hash,
        signal_dataset_id=row.signal_dataset_id,
        benchmark_dataset_id=row.benchmark_dataset_id,
        status=row.status,
        failure_code=row.failure_code,
        metrics=_metrics_from(row),
        created_at=row.created_at,
    )


def _trade_from(row: BacktestTradeRow) -> BacktestTrade:
    return BacktestTrade(
        sequence=row.sequence,
        signal_date=row.signal_date,
        execution_date=row.execution_date,
        action=SignalAction(row.action),
        reason=SignalReason(row.reason),
        quantity=row.quantity,
        price=row.price,
        gross_amount=row.gross_amount,
        fee=row.fee,
        slippage=row.slippage,
        tax=row.tax,
        skip_reason=TradeSkipReason(row.skip_reason) if row.skip_reason else None,
    )


@final
class PostgresBacktestReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresBacktestReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresBacktestReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def runs(self, limit: int) -> tuple[BacktestRunRecord, ...]:
        statement = (
            select(BacktestRunRow, InstrumentRow.symbol)
            .join(InstrumentRow, BacktestRunRow.instrument_id == InstrumentRow.id)
            .order_by(BacktestRunRow.created_at.desc(), BacktestRunRow.id)
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(_record_from(row[0], row[1]) for row in rows)

    async def run(self, run_id: UUID) -> BacktestRunRecord | None:
        statement = (
            select(BacktestRunRow, InstrumentRow.symbol)
            .join(InstrumentRow, BacktestRunRow.instrument_id == InstrumentRow.id)
            .where(BacktestRunRow.id == run_id)
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().one_or_none()
        return _record_from(row[0], row[1]) if row is not None else None

    async def trades(self, run_id: UUID) -> tuple[BacktestTrade, ...]:
        statement = (
            select(BacktestTradeRow)
            .where(BacktestTradeRow.run_id == run_id)
            .order_by(BacktestTradeRow.sequence)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(_trade_from(row) for row in rows)

    async def equity(self, run_id: UUID) -> tuple[EquityPoint, ...]:
        statement = (
            select(BacktestEquityRow)
            .where(BacktestEquityRow.run_id == run_id)
            .order_by(BacktestEquityRow.trading_date)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            EquityPoint(
                trading_date=row.trading_date,
                cash=row.cash,
                position_value=row.position_value,
                nav=row.nav,
            )
            for row in rows
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
