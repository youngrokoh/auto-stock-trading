from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.strategy_backtest_rows import (
    BacktestEquityRow,
    BacktestRunInstrumentRow,
    BacktestRunRow,
    BacktestTradeRow,
)

_REBALANCE_REASON: Final = "rebalance"

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.domain.strategies.backtest import BacktestTrade
    from auto_stock_trading.domain.strategies.backtest_metrics import EquityPoint
    from auto_stock_trading.domain.strategies.portfolio_backtest import PortfolioTrade
    from auto_stock_trading.domain.strategies.records import BacktestRunRecord, PortfolioRunRecord


@final
class PostgresBacktestStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresBacktestStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresBacktestStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save_run(
        self,
        record: BacktestRunRecord,
        trades: tuple[BacktestTrade, ...],
        equity: tuple[EquityPoint, ...],
    ) -> None:
        async with self._sessions.begin() as session:
            instrument_id = await session.scalar(
                select(InstrumentRow.id).where(InstrumentRow.symbol == record.symbol).limit(1)
            )
            if instrument_id is None:
                msg = f"unknown instrument {record.symbol}"
                raise LookupError(msg)
            metrics = record.metrics
            session.add(
                BacktestRunRow(
                    id=record.run_id,
                    strategy_name=record.strategy_name,
                    strategy_version=record.strategy_version,
                    parameters_json=record.parameters_json,
                    instrument_id=instrument_id,
                    benchmark_symbol=record.benchmark_symbol,
                    range_start=record.range_start,
                    range_end=record.range_end,
                    initial_cash=record.initial_cash,
                    signal_method=record.signal_method,
                    engine_version=record.engine_version,
                    cost_rule_versions=record.cost_rule_versions,
                    input_bar_version_hash=record.input_bar_version_hash,
                    action_version_hash=record.action_version_hash,
                    signal_dataset_id=record.signal_dataset_id,
                    benchmark_dataset_id=record.benchmark_dataset_id,
                    status=record.status,
                    failure_code=record.failure_code,
                    total_return_pct=metrics.total_return_pct if metrics else None,
                    pre_cost_return_pct=metrics.pre_cost_return_pct if metrics else None,
                    benchmark_return_pct=metrics.benchmark_return_pct if metrics else None,
                    excess_return_pct=metrics.excess_return_pct if metrics else None,
                    mdd_pct=metrics.mdd_pct if metrics else None,
                    sharpe=metrics.sharpe if metrics else None,
                    turnover_pct=metrics.turnover_pct if metrics else None,
                    total_fee=metrics.total_fee if metrics else None,
                    total_slippage=metrics.total_slippage if metrics else None,
                    total_tax=metrics.total_tax if metrics else None,
                    trade_count=metrics.trade_count if metrics else None,
                    created_at=record.created_at,
                )
            )
            await session.flush()
            session.add_all(
                BacktestTradeRow(
                    id=uuid4(),
                    run_id=record.run_id,
                    sequence=trade.sequence,
                    signal_date=trade.signal_date,
                    execution_date=trade.execution_date,
                    action=trade.action.value,
                    reason=trade.reason.value,
                    quantity=trade.quantity,
                    price=trade.price,
                    gross_amount=trade.gross_amount,
                    fee=trade.fee,
                    slippage=trade.slippage,
                    tax=trade.tax,
                    skip_reason=trade.skip_reason.value if trade.skip_reason else None,
                )
                for trade in trades
            )
            session.add_all(
                BacktestEquityRow(
                    id=uuid4(),
                    run_id=record.run_id,
                    trading_date=point.trading_date,
                    cash=point.cash,
                    position_value=point.position_value,
                    nav=point.nav,
                )
                for point in equity
            )

    async def save_portfolio_run(
        self,
        record: PortfolioRunRecord,
        trades: tuple[PortfolioTrade, ...],
        equity: tuple[EquityPoint, ...],
    ) -> None:
        """다종목 실행을 저장한다. 유니버스는 종목 행으로 남겨 조회·조인이 되게 한다."""
        async with self._sessions.begin() as session:
            instrument_ids = await _instrument_ids(session, record.universe)
            metrics = record.metrics
            session.add(
                BacktestRunRow(
                    id=record.run_id,
                    strategy_name=record.strategy_name,
                    strategy_version=record.strategy_version,
                    parameters_json=record.parameters_json,
                    instrument_id=None,
                    benchmark_symbol=record.benchmark_symbol,
                    range_start=record.range_start,
                    range_end=record.range_end,
                    initial_cash=record.initial_cash,
                    signal_method=record.signal_method,
                    engine_version=record.engine_version,
                    cost_rule_versions=record.cost_rule_versions,
                    input_bar_version_hash=record.input_bar_version_hash,
                    action_version_hash=record.action_version_hash,
                    signal_dataset_id=None,
                    benchmark_dataset_id=record.benchmark_dataset_id,
                    status=record.status,
                    failure_code=record.failure_code,
                    total_return_pct=metrics.total_return_pct if metrics else None,
                    pre_cost_return_pct=metrics.pre_cost_return_pct if metrics else None,
                    benchmark_return_pct=metrics.benchmark_return_pct if metrics else None,
                    excess_return_pct=metrics.excess_return_pct if metrics else None,
                    mdd_pct=metrics.mdd_pct if metrics else None,
                    sharpe=metrics.sharpe if metrics else None,
                    turnover_pct=metrics.turnover_pct if metrics else None,
                    total_fee=metrics.total_fee if metrics else None,
                    total_slippage=metrics.total_slippage if metrics else None,
                    total_tax=metrics.total_tax if metrics else None,
                    trade_count=metrics.trade_count if metrics else None,
                    created_at=record.created_at,
                )
            )
            await session.flush()
            session.add_all(
                BacktestRunInstrumentRow(
                    id=uuid4(),
                    run_id=record.run_id,
                    instrument_id=instrument_ids[symbol],
                    symbol=symbol,
                )
                for symbol in record.universe
            )
            session.add_all(
                BacktestTradeRow(
                    id=uuid4(),
                    run_id=record.run_id,
                    sequence=trade.sequence,
                    signal_date=trade.signal_date,
                    execution_date=trade.execution_date,
                    action=trade.action,
                    reason=_REBALANCE_REASON,
                    quantity=trade.quantity,
                    price=trade.price,
                    gross_amount=trade.gross_amount,
                    fee=trade.fee,
                    slippage=trade.slippage,
                    tax=trade.tax,
                    skip_reason=trade.skip_reason.value if trade.skip_reason else None,
                    symbol=trade.symbol,
                )
                for trade in trades
            )
            session.add_all(
                BacktestEquityRow(
                    id=uuid4(),
                    run_id=record.run_id,
                    trading_date=point.trading_date,
                    cash=point.cash,
                    position_value=point.position_value,
                    nav=point.nav,
                )
                for point in equity
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


async def _instrument_ids(session: AsyncSession, symbols: tuple[str, ...]) -> dict[str, UUID]:
    """유니버스 종목이 하나라도 없으면 실행을 저장하지 않는다(계보가 깨진다)."""
    result = await session.execute(
        select(InstrumentRow.symbol, InstrumentRow.id).where(InstrumentRow.symbol.in_(symbols))
    )
    found = dict(result.tuples().all())
    missing = [symbol for symbol in symbols if symbol not in found]
    if missing:
        message = f"unknown instruments {','.join(missing)}"
        raise LookupError(message)
    return found
