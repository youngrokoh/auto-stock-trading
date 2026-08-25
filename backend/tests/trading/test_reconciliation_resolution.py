"""사람이 확인한 재조정 문제 해소 판정. 순수 함수다(ADR-0018).

**대상이 좁은 것이 이 경로의 안전장치다.** 게이트를 막는 조건을 사람이 해제하는 표면이므로, 파생으로
풀 수 있는 문제는 받지 않는다 — 열린 주문의 문제를 해소로 표시하면 살아 있는 발산을 부기로 덮는
것이고, 이미 종결된 주문의 문제는 게이트가 세지 않으므로 해소 기록이 의미가 없다.
"""

from typing import Final

import pytest

from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.domain.orders.reconciliation import (
    ResolutionReason,
    ResolutionRejection,
    ResolutionRequest,
    ResolutionTarget,
    resolve_problems,
)

_BROKER_ORDER_ID: Final = "0000025643"


def _target(
    *,
    problem_count: int = 2,
    order_state: OrderState | None = None,
    resolved: bool = False,
) -> ResolutionTarget:
    return ResolutionTarget(
        broker_order_id=_BROKER_ORDER_ID,
        problem_count=problem_count,
        order_state=order_state,
        resolved=resolved,
    )


def _request(*, operator: str = "youngrokoh", evidence: str = "수동 주문") -> ResolutionRequest:
    return ResolutionRequest(
        broker_order_id=_BROKER_ORDER_ID,
        operator=operator,
        evidence=evidence,
    )


def test_a_broker_order_we_never_recorded_can_be_resolved() -> None:
    """우리 기록에 없는 주문번호만 해소 대상이다. 파생으로 풀 방법이 없는 유일한 경우다."""
    outcome = resolve_problems(_target(), _request())

    assert not isinstance(outcome, ResolutionRejection)
    assert outcome.broker_order_id == _BROKER_ORDER_ID
    assert outcome.problem_count == 2
    assert outcome.operator == "youngrokoh"


def test_one_resolution_covers_every_observation_of_the_same_divergence() -> None:
    """같은 주문번호의 문제 2건은 하나의 발산을 두 번 관측한 것이다. 설명도 하나다."""
    outcome = resolve_problems(_target(problem_count=5), _request())

    assert not isinstance(outcome, ResolutionRejection)
    assert outcome.problem_count == 5


def test_a_problem_on_a_still_open_order_is_refused() -> None:
    """살아 있는 발산을 부기로 덮지 않는다. 해소 방법은 주문을 종결시키는 것이다."""
    outcome = resolve_problems(_target(order_state=OrderState.SUBMITTED), _request())

    assert isinstance(outcome, ResolutionRejection)
    assert outcome.reason is ResolutionReason.ORDER_STILL_OPEN


def test_a_partially_filled_order_is_still_open() -> None:
    outcome = resolve_problems(_target(order_state=OrderState.PARTIALLY_FILLED), _request())

    assert isinstance(outcome, ResolutionRejection)
    assert outcome.reason is ResolutionReason.ORDER_STILL_OPEN


@pytest.mark.parametrize(
    "state",
    [OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED],
)
def test_a_problem_on_a_settled_order_is_refused(state: OrderState) -> None:
    """게이트가 이미 세지 않는다. 의미 없는 사람 확인이 쌓이면 확인이 형식이 된다."""
    outcome = resolve_problems(_target(order_state=state), _request())

    assert isinstance(outcome, ResolutionRejection)
    assert outcome.reason is ResolutionReason.ALREADY_SETTLED


def test_a_number_with_no_problem_recorded_is_refused() -> None:
    """미리 해소를 선언해 두는 경로를 만들지 않는다."""
    outcome = resolve_problems(_target(problem_count=0), _request())

    assert isinstance(outcome, ResolutionRejection)
    assert outcome.reason is ResolutionReason.NO_PROBLEM_RECORDED


def test_resolving_twice_is_refused() -> None:
    outcome = resolve_problems(_target(resolved=True), _request())

    assert isinstance(outcome, ResolutionRejection)
    assert outcome.reason is ResolutionReason.ALREADY_RESOLVED


@pytest.mark.parametrize(("operator", "evidence"), [("", "수동 주문"), ("사람", ""), (" ", " ")])
def test_missing_operator_or_evidence_is_refused(operator: str, evidence: str) -> None:
    """근거 없는 해소는 조건을 지우는 행위다. ADR-0010과 같은 요구다."""
    outcome = resolve_problems(_target(), _request(operator=operator, evidence=evidence))

    assert isinstance(outcome, ResolutionRejection)
    assert outcome.reason is ResolutionReason.EVIDENCE_REQUIRED
