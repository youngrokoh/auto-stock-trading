"""사람이 확인한 대조 종결 이벤트. 증권사 사실과 구분해 기록한다(ADR-0010)."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_0017"
down_revision: str | None = "20260819_0016"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_EVENT_TYPES = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation')"
)
_PREVIOUS_EVENT_TYPES = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem', 'listener_state')"
)


def upgrade() -> None:
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
