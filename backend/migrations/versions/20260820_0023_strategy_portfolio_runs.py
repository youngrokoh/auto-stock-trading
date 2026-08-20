"""다종목 백테스트 실행 기록. 유니버스를 문자열이 아니라 행으로 보존한다(계약 v2)."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0023"
down_revision: str | None = "20260820_0022"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # 다종목 실행은 대표 종목이 없다. 단일 종목 전략은 이 열을 계속 쓴다.
    op.alter_column("backtest_run", "instrument_id", nullable=True, schema="strategy")
    _ = op.create_table(
        "backtest_run_instrument",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("strategy.backtest_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.UniqueConstraint("run_id", "instrument_id", name="uq_backtest_run_instrument"),
        schema="strategy",
    )
    op.create_index(
        "ix_backtest_run_instrument_symbol",
        "backtest_run_instrument",
        ["symbol"],
        schema="strategy",
    )
    # 체결 기록도 종목을 가져야 한다. 단일 종목 실행은 실행의 종목과 같다.
    op.add_column(
        "backtest_trade",
        sa.Column("symbol", sa.String(9)),
        schema="strategy",
    )


def downgrade() -> None:
    op.drop_column("backtest_trade", "symbol", schema="strategy")
    op.drop_index(
        "ix_backtest_run_instrument_symbol",
        table_name="backtest_run_instrument",
        schema="strategy",
    )
    op.drop_table("backtest_run_instrument", schema="strategy")
    op.alter_column("backtest_run", "instrument_id", nullable=False, schema="strategy")
