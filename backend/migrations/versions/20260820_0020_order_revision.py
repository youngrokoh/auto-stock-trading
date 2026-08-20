"""정정 시점 위험판정 보존. 정책 §7은 모든 주문 시도의 규칙 판정을 요구한다(ADR-0011)."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0020"
down_revision: str | None = "20260820_0019"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ATTEMPT_POSITIVE = "attempt >= 1"


def upgrade() -> None:
    # 기존 판정은 모두 계획 시점(1회차)이다.
    op.add_column(
        "risk_decision",
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        schema="trading",
    )
    op.create_check_constraint(
        "ck_risk_decision_attempt",
        "risk_decision",
        sa.text(_ATTEMPT_POSITIVE),
        schema="trading",
    )
    op.drop_constraint("uq_risk_decision_rule", "risk_decision", schema="trading", type_="unique")
    op.create_unique_constraint(
        "uq_risk_decision_rule",
        "risk_decision",
        ["order_id", "rule_code", "attempt"],
        schema="trading",
    )
    op.add_column(
        "order",
        sa.Column("revision_count", sa.Integer, nullable=False, server_default="0"),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_column("order", "revision_count", schema="trading")
    op.drop_constraint("uq_risk_decision_rule", "risk_decision", schema="trading", type_="unique")
    op.create_unique_constraint(
        "uq_risk_decision_rule",
        "risk_decision",
        ["order_id", "rule_code"],
        schema="trading",
    )
    op.drop_constraint(
        "ck_risk_decision_attempt",
        "risk_decision",
        schema="trading",
        type_="check",
    )
    op.drop_column("risk_decision", "attempt", schema="trading")
