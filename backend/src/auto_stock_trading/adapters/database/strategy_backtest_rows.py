from datetime import date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class BacktestRunRow(Base):
    __tablename__: str = "backtest_run"
    __table_args__: tuple[dict[str, str]] = ({"schema": "strategy"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(40), index=True)
    strategy_version: Mapped[str] = mapped_column(String(16))
    parameters_json: Mapped[str] = mapped_column(Text)
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
    )
    benchmark_symbol: Mapped[str] = mapped_column(String(9))
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    signal_method: Mapped[str] = mapped_column(String(24))
    engine_version: Mapped[str] = mapped_column(String(24))
    cost_rule_versions: Mapped[str] = mapped_column(Text)
    input_bar_version_hash: Mapped[str] = mapped_column(String(64))
    action_version_hash: Mapped[str] = mapped_column(String(64))
    signal_dataset_id: Mapped[UUID | None] = mapped_column()
    benchmark_dataset_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    total_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    pre_cost_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    benchmark_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    excess_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    mdd_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    sharpe: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    turnover_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    total_fee: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    total_slippage: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    total_tax: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    trade_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class BacktestTradeRow(Base):
    __tablename__: str = "backtest_trade"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("run_id", "sequence", name="uq_backtest_trade_sequence"),
        {"schema": "strategy"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy.backtest_run.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    signal_date: Mapped[date] = mapped_column(Date)
    execution_date: Mapped[date | None] = mapped_column(Date)
    action: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(String(24))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    slippage: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    tax: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    skip_reason: Mapped[str | None] = mapped_column(String(32))


@final
class BacktestEquityRow(Base):
    __tablename__: str = "backtest_equity"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("run_id", "trading_date", name="uq_backtest_equity_date"),
        {"schema": "strategy"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy.backtest_run.id", ondelete="CASCADE"),
        index=True,
    )
    trading_date: Mapped[date] = mapped_column(Date)
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    position_value: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    nav: Mapped[Decimal] = mapped_column(Numeric(24, 0))
