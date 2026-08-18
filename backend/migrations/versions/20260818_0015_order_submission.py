"""주문 제출·체결 동기화 컬럼. 증권사 사실을 저장하되 계좌번호 원문은 남기지 않는다."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0015"
down_revision: str | None = "20260818_0014"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_SUBMITTED_STATES = "('submitted', 'partially_filled', 'filled')"
_SUBMITTED_FIELDS = (
    f"state NOT IN {_SUBMITTED_STATES}"
    " OR (broker_order_id IS NOT NULL AND broker_org_no IS NOT NULL"
    " AND submitted_at IS NOT NULL)"
)
_EVENT_TYPES = "event_type IN ('state_change', 'api_failure', 'reconcile_problem')"
_FILL_QUANTITY = (
    "filled_quantity >= 0 AND filled_quantity <= quantity"
    " AND (filled_quantity = 0 OR average_fill_price > 0)"
)


def upgrade() -> None:
    op.add_column(
        "order",
        sa.Column("broker_org_no", sa.String(8), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order",
        sa.Column("broker_order_time", sa.String(6), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.add_column(
        "order",
        sa.Column("average_fill_price", sa.Numeric(24, 8), nullable=True),
        schema="trading",
    )
    op.create_index(
        "uq_order_broker_order_id",
        "order",
        ["broker_order_id"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("broker_order_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_order_submitted_fields",
        "order",
        sa.text(_SUBMITTED_FIELDS),
        schema="trading",
    )
    op.create_check_constraint(
        "ck_order_fill_quantity",
        "order",
        sa.text(_FILL_QUANTITY),
        schema="trading",
    )
    op.drop_constraint(
        "ck_automation_event_type",
        "automation_event",
        schema="trading",
        type_="check",
    )
    op.create_check_constraint(
        "ck_automation_event_type",
        "automation_event",
        sa.text(_EVENT_TYPES),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_automation_event_type",
        "automation_event",
        schema="trading",
        type_="check",
    )
    op.create_check_constraint(
        "ck_automation_event_type",
        "automation_event",
        sa.text("event_type IN ('state_change', 'api_failure')"),
        schema="trading",
    )
    op.drop_constraint("ck_order_fill_quantity", "order", schema="trading", type_="check")
    op.drop_constraint("ck_order_submitted_fields", "order", schema="trading", type_="check")
    op.drop_index("uq_order_broker_order_id", "order", schema="trading")
    op.drop_column("order", "average_fill_price", schema="trading")
    op.drop_column("order", "submitted_at", schema="trading")
    op.drop_column("order", "broker_order_time", schema="trading")
    op.drop_column("order", "broker_org_no", schema="trading")
