"""예약 제출이 차단된 사실을 이벤트로 남긴다(ADR-0015 결정 6).

사람이 없는 동안 도는 경로에서는 조용한 실패가 가장 위험하다. 차단은 지금까지 CLI 출력으로만
드러났고 저장되지 않았다 — 자동 실행에서는 그 출력을 보는 사람이 없다.

Revision ID: 20260825_0030
Revises: 20260825_0029
"""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0030"
down_revision: str | None = "20260825_0029"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_EVENT_TYPES: Final = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation', 'schedule_blocked')"
)
_PREVIOUS_EVENT_TYPES: Final = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation')"
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
