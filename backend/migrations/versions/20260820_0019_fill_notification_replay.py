"""대조 실패로 반영되지 않은 통보의 재반영 시점. 원래 문제 기록은 그대로 남긴다."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0019"
down_revision: str | None = "20260820_0018"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# 문제가 기록된 통보만 재반영 대상이며, 재반영은 한 번만 일어난다.
_REPLAY_ONLY_PROBLEMS = "resolved_at IS NULL OR problem IS NOT NULL"


def upgrade() -> None:
    op.add_column(
        "fill_notification",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.create_check_constraint(
        "ck_fill_notification_replay",
        "fill_notification",
        sa.text(_REPLAY_ONLY_PROBLEMS),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_fill_notification_replay",
        "fill_notification",
        schema="trading",
        type_="check",
    )
    op.drop_column("fill_notification", "resolved_at", schema="trading")
