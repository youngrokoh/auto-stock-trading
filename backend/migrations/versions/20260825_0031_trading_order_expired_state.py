"""세션 종료로 종결된 주문 상태를 추가한다(ADR-0017 결정 4).

정규장이 끝나 더 체결될 수 없음이 계좌 단위 집계로 확인된 주문은 종결 상태로 옮긴다. 기존
`canceled`를 재사용하지 않는다 — 우리가 취소한 것이 아니므로 그렇게 적으면 사실이 아니다.

제약은 `order`와 `order_event` 두 곳에 걸려 있다. 이벤트 쪽을 빼면 전이는 되는데 그 사실을 남길 수
없다.

Revision ID: 20260825_0031
Revises: 20260825_0030
"""

from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0031"
down_revision: str | None = "20260825_0030"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_STATES: Final = (
    "state IN ('planned', 'submitted', 'partially_filled', 'filled', 'rejected',"
    " 'canceled', 'expired')"
)
_PREVIOUS_STATES: Final = (
    "state IN ('planned', 'submitted', 'partially_filled', 'filled', 'rejected', 'canceled')"
)
_CONSTRAINTS: Final = (
    ("ck_order_state", "order"),
    ("ck_order_event_state", "order_event"),
)


def upgrade() -> None:
    for name, table in _CONSTRAINTS:
        op.drop_constraint(name, table, schema="trading", type_="check")
        op.create_check_constraint(name, table, sa.text(_STATES), schema="trading")


def downgrade() -> None:
    for name, table in _CONSTRAINTS:
        op.drop_constraint(name, table, schema="trading", type_="check")
        op.create_check_constraint(name, table, sa.text(_PREVIOUS_STATES), schema="trading")
