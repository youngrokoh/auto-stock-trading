import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0013"
down_revision: str | None = "20260818_0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "backtest_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("strategy_name", sa.String(40), nullable=False),
        sa.Column("strategy_version", sa.String(16), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("benchmark_symbol", sa.String(9), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("initial_cash", sa.Numeric(24, 0), nullable=False),
        sa.Column("signal_method", sa.String(24), nullable=False),
        sa.Column("engine_version", sa.String(24), nullable=False),
        sa.Column("cost_rule_versions", sa.Text(), nullable=False),
        sa.Column("input_bar_version_hash", sa.String(64), nullable=False),
        sa.Column("action_version_hash", sa.String(64), nullable=False),
        sa.Column("signal_dataset_id", sa.Uuid()),
        sa.Column("benchmark_dataset_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("total_return_pct", sa.Numeric(16, 2)),
        sa.Column("pre_cost_return_pct", sa.Numeric(16, 2)),
        sa.Column("benchmark_return_pct", sa.Numeric(16, 2)),
        sa.Column("excess_return_pct", sa.Numeric(16, 2)),
        sa.Column("mdd_pct", sa.Numeric(16, 2)),
        sa.Column("sharpe", sa.Numeric(16, 4)),
        sa.Column("turnover_pct", sa.Numeric(16, 2)),
        sa.Column("total_fee", sa.Numeric(24, 0)),
        sa.Column("total_slippage", sa.Numeric(24, 0)),
        sa.Column("total_tax", sa.Numeric(24, 0)),
        sa.Column("trade_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("range_start <= range_end", name="ck_backtest_run_range"),
        sa.CheckConstraint("initial_cash > 0", name="ck_backtest_run_initial_cash"),
        sa.CheckConstraint(
            "status IN ('completed', 'failed')",
            name="ck_backtest_run_status",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR failure_code IS NOT NULL",
            name="ck_backtest_run_failure_code",
        ),
        schema="strategy",
    )
    op.create_index(
        "ix_backtest_run_lookup",
        "backtest_run",
        ["strategy_name", "created_at"],
        schema="strategy",
    )

    _ = op.create_table(
        "backtest_trade",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("strategy.backtest_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("execution_date", sa.Date()),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(24, 8)),
        sa.Column("gross_amount", sa.Numeric(24, 0), nullable=False),
        sa.Column("fee", sa.Numeric(24, 0), nullable=False),
        sa.Column("slippage", sa.Numeric(24, 0), nullable=False),
        sa.Column("tax", sa.Numeric(24, 0), nullable=False),
        sa.Column("skip_reason", sa.String(32)),
        sa.UniqueConstraint("run_id", "sequence", name="uq_backtest_trade_sequence"),
        sa.CheckConstraint("action IN ('buy', 'sell')", name="ck_backtest_trade_action"),
        sa.CheckConstraint("quantity >= 0", name="ck_backtest_trade_quantity"),
        sa.CheckConstraint(
            "(skip_reason IS NULL) <> (execution_date IS NULL)",
            name="ck_backtest_trade_execution",
        ),
        schema="strategy",
    )

    _ = op.create_table(
        "backtest_equity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("strategy.backtest_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Numeric(24, 0), nullable=False),
        sa.Column("position_value", sa.Numeric(24, 0), nullable=False),
        sa.Column("nav", sa.Numeric(24, 0), nullable=False),
        sa.UniqueConstraint("run_id", "trading_date", name="uq_backtest_equity_date"),
        schema="strategy",
    )


def downgrade() -> None:
    op.drop_table("backtest_equity", schema="strategy")
    op.drop_table("backtest_trade", schema="strategy")
    op.drop_index("ix_backtest_run_lookup", "backtest_run", schema="strategy")
    op.drop_table("backtest_run", schema="strategy")
