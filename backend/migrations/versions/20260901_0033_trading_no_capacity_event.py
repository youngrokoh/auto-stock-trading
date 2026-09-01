"""넣을 자리가 없어 계획하지 않은 후보를 사실로 남긴다(ADR-0020 결정 2).

거절로 세지 않기로 하면서 사실까지 지우면, 전략이 매일 통과할 수 없는 것을 요구하는 상태가 아무 흔적
없이 지나간다. 거절 주문 행 대신 이 이벤트가 그 자리를 대신한다.

Revision ID: 20260901_0033
Revises: 20260825_0032
"""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0033"
down_revision: str | None = "20260825_0032"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_EVENT_TYPES: Final = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation', 'schedule_blocked', 'reconcile_resolved',"
    " 'no_capacity')"
)
_PREVIOUS_EVENT_TYPES: Final = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation', 'schedule_blocked', 'reconcile_resolved')"
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
