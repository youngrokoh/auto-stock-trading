"""실시간 체결통보 저장. 복호화 본문은 개인정보를 마스킹한 뒤에만 저장한다."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_0016"
down_revision: str | None = "20260818_0015"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_EVENT_TYPES = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem', 'listener_state')"
)
_PREVIOUS_EVENT_TYPES = "event_type IN ('state_change', 'api_failure', 'reconcile_problem')"
_NOTIFICATION_KINDS = "notification_kind IN ('order', 'execution')"
_NOTIFICATION_AMOUNTS = "quantity >= 0 AND order_quantity >= 0 AND price >= 0"
# 계약의 마스킹 규칙: 인덱스 0(고객ID)·1(계좌번호)는 항상 '***'로 치환된 뒤 저장된다.
_NOTIFICATION_MASKED = "masked_payload LIKE '***^***^%'"
_SESSION_STATES = "state IN ('connected', 'disconnected', 'closed')"
_SESSION_END = "state = 'connected' OR ended_at IS NOT NULL"


def upgrade() -> None:
    _ = op.create_table(
        "fill_notification",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("account_reference", sa.String(12), nullable=False),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("trading.order.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("broker_order_id", sa.String(40), nullable=False),
        sa.Column("original_broker_order_id", sa.String(40), nullable=True),
        sa.Column("notification_kind", sa.String(12), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("order_quantity", sa.Integer(), nullable=False),
        sa.Column("broker_event_time", sa.String(6), nullable=False),
        sa.Column("rejected", sa.Boolean(), nullable=False),
        sa.Column("revise_code", sa.String(4), nullable=False),
        sa.Column("accept_code", sa.String(4), nullable=False),
        sa.Column("branch_no", sa.String(8), nullable=False),
        sa.Column("masked_payload", sa.Text(), nullable=False),
        sa.Column("problem", sa.String(40), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_NOTIFICATION_KINDS, name="ck_fill_notification_kind"),
        sa.CheckConstraint(_NOTIFICATION_AMOUNTS, name="ck_fill_notification_amounts"),
        sa.CheckConstraint(_NOTIFICATION_MASKED, name="ck_fill_notification_masked"),
        schema="trading",
    )
    op.create_index(
        "ix_fill_notification_broker_order",
        "fill_notification",
        ["broker_order_id", "received_at"],
        schema="trading",
    )
    op.create_index(
        "ix_fill_notification_environment",
        "fill_notification",
        ["environment", "received_at"],
        schema="trading",
    )
    _ = op.create_table(
        "notification_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("transaction_id", sa.String(16), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnect_reason", sa.String(40), nullable=True),
        sa.CheckConstraint(_SESSION_STATES, name="ck_notification_session_state"),
        sa.CheckConstraint(_SESSION_END, name="ck_notification_session_end"),
        schema="trading",
    )
    op.create_index(
        "uq_notification_session_connected",
        "notification_session",
        ["environment"],
        unique=True,
        schema="trading",
        postgresql_where=sa.text("state = 'connected'"),
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
        sa.text(_PREVIOUS_EVENT_TYPES),
        schema="trading",
    )
    op.drop_index("uq_notification_session_connected", "notification_session", schema="trading")
    op.drop_table("notification_session", schema="trading")
    op.drop_index("ix_fill_notification_environment", "fill_notification", schema="trading")
    op.drop_index("ix_fill_notification_broker_order", "fill_notification", schema="trading")
    op.drop_table("fill_notification", schema="trading")
