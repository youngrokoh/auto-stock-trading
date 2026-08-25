"""실주문 신호를 저장된 사실로 남긴다(ADR-0016 결정 2).

계획 시점에 즉석 계산하지 않는다. 어떤 확정 봉 버전으로 어떤 점수가 나와 어떤 목표가 됐는지가
주문과 별개 사실로 남아야 감사가 성립하고, 계획을 다시 실행해도 후보가 흔들리지 않는다.

Revision ID: 20260825_0029
Revises: 20260824_0028
"""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0029"
down_revision: str | None = "20260824_0028"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ENVIRONMENTS: Final = "('paper', 'live')"


def upgrade() -> None:
    _ = op.create_table(
        "live_signal",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("strategy_name", sa.String(40), nullable=False),
        sa.Column("strategy_version", sa.String(16), nullable=False),
        sa.Column("parameters_json", sa.String(1000), nullable=False),
        # 신호의 기준 거래일. 확정 봉은 전날까지만 있으므로 T-1이다.
        sa.Column("basis_date", sa.Date(), nullable=False),
        # 목표를 정한 완결된 월말 회차. `basis_date`와 다를 수 있다(회차 사이의 날).
        sa.Column("rebalance_date", sa.Date(), nullable=False),
        sa.Column("bar_version_hash", sa.String(64), nullable=False),
        # 백테스트-실주문 괴리 관측용 기준 종가(ADR-0016 결정 7).
        sa.Column("basis_close_json", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "environment",
            "strategy_name",
            "strategy_version",
            "basis_date",
            name="uq_live_signal_basis",
        ),
        sa.CheckConstraint(f"environment IN {_ENVIRONMENTS}", name="ck_live_signal_environment"),
        schema="strategy",
    )
    _ = op.create_table(
        "live_signal_target",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "signal_id",
            sa.Uuid(),
            sa.ForeignKey("strategy.live_signal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(9), nullable=False),
        sa.Column("score", sa.Numeric(24, 8), nullable=False),
        sa.UniqueConstraint("signal_id", "symbol", name="uq_live_signal_target_symbol"),
        schema="strategy",
    )


def downgrade() -> None:
    op.drop_table("live_signal_target", schema="strategy")
    op.drop_table("live_signal", schema="strategy")
