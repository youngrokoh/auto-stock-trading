"""세션 종료 시 열린 주문 처리와 계좌 단위 재대조(ADR-0017).

**집계 일치만이 종결 근거다.** 정규장이 끝나면 미체결 주문은 체결될 수 없지만 그것은 우리가 관측한
사실이 아니다. 증권사 당일 집계가 우리 내부 체결 합계와 맞으면 "우리가 미체결로 아는 주문이 실제로도
체결되지 않았다"가 관측으로 확인되므로 그때만 종결한다. 어긋나면 사람 확인을 남긴다.
"""

from decimal import Decimal

from auto_stock_trading.domain.orders.fills import OrderSnapshot, ReconcileProblem
from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.domain.orders.session_close import (
    AggregateVerdict,
    BrokerDailyTotals,
    InternalDailyTotals,
    close_session_orders,
    compare_daily_totals,
)


def _internal(quantity: int, amount: str) -> InternalDailyTotals:
    return InternalDailyTotals(filled_quantity=quantity, filled_amount=Decimal(amount))


def _broker(quantity: int, amount: str) -> BrokerDailyTotals:
    return BrokerDailyTotals(filled_quantity=quantity, filled_amount=Decimal(amount))


def _order(
    client_order_id: str,
    *,
    quantity: int = 1,
    filled: int = 0,
    state: OrderState = OrderState.SUBMITTED,
) -> OrderSnapshot:
    return OrderSnapshot(
        client_order_id=client_order_id,
        broker_order_id="0000009931",
        symbol="005930",
        quantity=quantity,
        filled_quantity=filled,
        average_fill_price=None,
        state=state,
    )


def test_matching_totals_are_matched() -> None:
    """2026-08-25 실측: 우리 2주·498,000원과 증권사 집계가 정확히 같았다."""
    verdict = compare_daily_totals(_internal(2, "498000"), _broker(2, "498000"))

    assert verdict is AggregateVerdict.MATCHED


def test_quantity_difference_is_a_mismatch() -> None:
    verdict = compare_daily_totals(_internal(2, "498000"), _broker(3, "498000"))

    assert verdict is AggregateVerdict.MISMATCHED


def test_amount_difference_is_a_mismatch() -> None:
    """수량이 같아도 금액이 다르면 어느 쪽이 틀렸는지 모른다. 맞추지 않고 불일치로 둔다."""
    verdict = compare_daily_totals(_internal(2, "498000"), _broker(2, "497000"))

    assert verdict is AggregateVerdict.MISMATCHED


def test_absent_totals_are_unavailable_not_matched() -> None:
    """집계가 없는 것은 일치가 아니다. 빈 응답을 성공으로 읽지 않는다."""
    verdict = compare_daily_totals(_internal(0, "0"), None)

    assert verdict is AggregateVerdict.UNAVAILABLE


def test_both_sides_empty_still_matches() -> None:
    """주문이 없던 날은 0 == 0이다. 집계가 오면 대조는 수행된 것이다."""
    verdict = compare_daily_totals(_internal(0, "0"), _broker(0, "0"))

    assert verdict is AggregateVerdict.MATCHED


def test_matched_verdict_expires_open_orders() -> None:
    outcomes = close_session_orders((_order("a"),), AggregateVerdict.MATCHED)

    assert len(outcomes) == 1
    assert outcomes[0].state is OrderState.EXPIRED
    assert outcomes[0].closed is True
    assert outcomes[0].problem is None


def test_expiry_preserves_the_filled_part_of_a_partial_fill() -> None:
    """부분 체결의 체결분은 사실이다. 남은 수량이 체결되지 않는다는 것만 새 사실이다."""
    outcomes = close_session_orders(
        (_order("a", quantity=5, filled=2, state=OrderState.PARTIALLY_FILLED),),
        AggregateVerdict.MATCHED,
    )

    assert outcomes[0].state is OrderState.EXPIRED
    assert outcomes[0].filled_quantity == 2


def test_mismatched_verdict_never_closes_and_records_a_problem() -> None:
    outcomes = close_session_orders((_order("a"),), AggregateVerdict.MISMATCHED)

    assert outcomes[0].closed is False
    assert outcomes[0].state is OrderState.SUBMITTED
    assert outcomes[0].problem is ReconcileProblem.DAILY_TOTALS_MISMATCH


def test_unavailable_verdict_never_closes_and_records_a_problem() -> None:
    """집계가 없으면 종결 근거가 없다. 증권사가 어긋난 것과 근거가 없는 것을 다른 코드로 남긴다."""
    outcomes = close_session_orders((_order("a"),), AggregateVerdict.UNAVAILABLE)

    assert outcomes[0].closed is False
    assert outcomes[0].problem is ReconcileProblem.DAILY_TOTALS_UNAVAILABLE


def test_no_open_orders_produces_no_outcomes() -> None:
    """열린 주문이 없으면 불일치여도 종결할 대상이 없다. 정지 판단은 호출자가 한다."""
    assert close_session_orders((), AggregateVerdict.MISMATCHED) == ()


def test_terminal_orders_are_not_touched() -> None:
    """이미 종결된 주문을 다시 종결하지 않는다."""
    outcomes = close_session_orders(
        (_order("a", filled=1, state=OrderState.FILLED),),
        AggregateVerdict.MATCHED,
    )

    assert outcomes == ()
