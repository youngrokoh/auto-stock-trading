"""사람이 확인한 재조정 문제 해소를 별도 사실로 남긴다(ADR-0018 결정 1·2).

문제 이벤트를 고치거나 지우지 않는다. 문제가 발생한 것은 일어난 일이고, 나중에 설명이 붙었다는 것은
다른 사실이다. 그래서 문제 행에 `resolved_at`을 더하지 않는다.

해소는 **증권사 주문번호 단위**이므로 그 키를 가진 전용 테이블에 담는다. 초안은 자동매매 이벤트만
언급했지만, 이벤트 한 곳에 담으면 주문번호를 `detail` 문자열에 끼워 넣고 게이트가 `LIKE`로
맞춰야 한다 — 운영자·근거까지 같은 문자열에 포장된다. 전용 테이블은 세 값에 각자의 컬럼을 주고,
유일 제약이 중복 해소를 읽기 시점 검사가 아니라 **DB 보장**으로 만든다. 감사·알림용
`reconcile_resolved` 이벤트는 그대로 함께 남기므로 append-only 성질은 유지된다.

Revision ID: 20260825_0032
Revises: 20260825_0031
"""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0032"
down_revision: str | None = "20260825_0031"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_EVENT_TYPES: Final = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation', 'schedule_blocked', 'reconcile_resolved')"
)
_PREVIOUS_EVENT_TYPES: Final = (
    "event_type IN ('state_change', 'api_failure', 'reconcile_problem',"
    " 'listener_state', 'attestation', 'schedule_blocked')"
)


def upgrade() -> None:
    _ = op.create_table(
        "reconcile_resolution",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("broker_order_id", sa.String(40), nullable=False),
        sa.Column("operator", sa.String(64), nullable=False),
        sa.Column("evidence", sa.String(500), nullable=False),
        sa.Column("problem_count", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "environment",
            "broker_order_id",
            name="uq_reconcile_resolution_order",
        ),
        sa.CheckConstraint("length(trim(operator)) > 0", name="ck_reconcile_resolution_operator"),
        sa.CheckConstraint("length(trim(evidence)) > 0", name="ck_reconcile_resolution_evidence"),
        sa.CheckConstraint("problem_count > 0", name="ck_reconcile_resolution_problems"),
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
    op.drop_table("reconcile_resolution", schema="trading")
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
