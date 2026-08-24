"""외부 알림 아웃박스와 투영 워터마크 (ADR-0014).

아웃박스 행은 폴러가 투영한다. 주문·자동매매 쓰기 경로는 변경되지 않으며, 중복 투영은
`(environment, source, source_id)` 유일 제약이 막는다.

Revision ID: 20260824_0028
Revises: 20260823_0027
"""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0028"
down_revision: str | None = "20260823_0027"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ENVIRONMENTS: Final = "('paper', 'live')"
_SOURCES: Final = "('order_event', 'automation_event', 'risk_decision')"
_STATES: Final = "('pending', 'sent', 'failed')"
_SEVERITIES: Final = "('info', 'warning')"


def upgrade() -> None:
    _ = op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("state", sa.String(8), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("event_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "environment",
            "source",
            "source_id",
            name="uq_notification_outbox_event",
        ),
        sa.CheckConstraint(
            f"environment IN {_ENVIRONMENTS}",
            name="ck_notification_outbox_environment",
        ),
        sa.CheckConstraint(f"source IN {_SOURCES}", name="ck_notification_outbox_source"),
        sa.CheckConstraint(f"state IN {_STATES}", name="ck_notification_outbox_state"),
        sa.CheckConstraint(f"severity IN {_SEVERITIES}", name="ck_notification_outbox_severity"),
        schema="trading",
    )
    _ = op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["environment", "state", "event_occurred_at"],
        schema="trading",
    )
    _ = op.create_table(
        "notification_watermark",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("projected_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("environment", name="uq_notification_watermark_environment"),
        sa.CheckConstraint(
            f"environment IN {_ENVIRONMENTS}",
            name="ck_notification_watermark_environment",
        ),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_table("notification_watermark", schema="trading")
    op.drop_index(
        "ix_notification_outbox_pending",
        table_name="notification_outbox",
        schema="trading",
    )
    op.drop_table("notification_outbox", schema="trading")
