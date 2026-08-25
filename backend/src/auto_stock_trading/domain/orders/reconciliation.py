"""사람이 확인한 재조정 문제 해소 판정. 순수 함수다(ADR-0018).

게이트는 **막는 것이 내용**이다. 사람이 조건을 해제할 수 있게 만들면 진짜 발산도 "설명했다"는
한 줄로 지워질 수 있으므로, 안전장치는 **대상을 좁히는 것**이다 — 파생으로 풀 수 있는 문제는
받지 않는다.

받는 것은 우리 기록에 아예 없는 증권사 주문번호뿐이다. 그것만이 파생으로 풀 방법이 없다.
해소는 주문번호 단위이며 같은 번호의 문제 여러 건은 **하나의 발산을 여러 번 관측한 것**이므로
설명도 하나다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from auto_stock_trading.domain.orders.models import OrderState

_OPEN_STATES: Final = frozenset({OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED})


class ResolutionReason(StrEnum):
    """거부 사유. 화면·감사·CLI가 같은 문자열을 쓴다."""

    NO_PROBLEM_RECORDED = "NO_PROBLEM_RECORDED"
    ORDER_STILL_OPEN = "ORDER_STILL_OPEN"
    ALREADY_SETTLED = "ALREADY_SETTLED"
    ALREADY_RESOLVED = "ALREADY_RESOLVED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"


@dataclass(frozen=True, slots=True)
class ResolutionTarget:
    """저장된 사실에서 읽은 대상. `order_state`가 `None`이면 우리 기록에 없는 주문번호다."""

    broker_order_id: str
    problem_count: int
    order_state: OrderState | None
    resolved: bool


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """사람이 넣는 값. 시스템이 추정하지 않는다."""

    broker_order_id: str
    operator: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    broker_order_id: str
    problem_count: int
    operator: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ResolutionRejection:
    reason: ResolutionReason


def _reason(target: ResolutionTarget, request: ResolutionRequest) -> ResolutionReason | None:
    if not request.operator.strip() or not request.evidence.strip():
        return ResolutionReason.EVIDENCE_REQUIRED
    if target.problem_count == 0:
        # 미리 해소를 선언해 두는 경로를 만들지 않는다.
        return ResolutionReason.NO_PROBLEM_RECORDED
    if target.resolved:
        return ResolutionReason.ALREADY_RESOLVED
    state = target.order_state
    if state is None:
        return None
    if state in _OPEN_STATES:
        # 살아 있는 발산을 부기로 덮지 않는다. 해소 방법은 주문을 종결시키는 것이다.
        return ResolutionReason.ORDER_STILL_OPEN
    # 게이트가 이미 세지 않는다. 의미 없는 사람 확인이 쌓이면 확인이 형식이 된다.
    return ResolutionReason.ALREADY_SETTLED


def resolve_problems(
    target: ResolutionTarget,
    request: ResolutionRequest,
) -> ResolutionOutcome | ResolutionRejection:
    """사람이 남긴 설명을 해소 사실로 바꾼다. 대상이 아니면 거부한다."""
    reason = _reason(target, request)
    if reason is not None:
        return ResolutionRejection(reason=reason)
    return ResolutionOutcome(
        broker_order_id=target.broker_order_id,
        problem_count=target.problem_count,
        operator=request.operator.strip(),
        evidence=request.evidence.strip(),
    )
