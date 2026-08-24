"""증권사 체결 사실을 내부 주문 상태로 옮기는 순수 함수. 값을 추정하지 않는다."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.orders.models import OrderState

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal

_TERMINAL_STATES: Final = frozenset({OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELED})


class ReconcileProblem(StrEnum):
    """설명할 수 없는 불일치. 자동으로 정리하지 않고 자동매매를 차단한다."""

    UNKNOWN_BROKER_ORDER = "UNKNOWN_BROKER_ORDER"
    FILL_EXCEEDS_ORDER = "FILL_EXCEEDS_ORDER"
    FILL_DECREASED = "FILL_DECREASED"
    TERMINAL_STATE_CHANGED = "TERMINAL_STATE_CHANGED"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    ORDER_QUANTITY_MISMATCH = "ORDER_QUANTITY_MISMATCH"
    NOTIFICATION_UNPARSABLE = "NOTIFICATION_UNPARSABLE"
    NOTIFICATION_GAP = "NOTIFICATION_GAP"


@dataclass(frozen=True, slots=True)
class BrokerFill:
    """일별주문체결조회 한 행을 정규화한 증권사 사실."""

    broker_order_id: str
    symbol: str
    order_quantity: int
    filled_quantity: int
    remaining_quantity: int
    rejected_quantity: int
    canceled: bool
    average_fill_price: Decimal | None


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """동기화 대상 주문의 내부 현재 상태."""

    client_order_id: str
    broker_order_id: str | None
    symbol: str
    quantity: int
    filled_quantity: int
    average_fill_price: Decimal | None
    state: OrderState


@dataclass(frozen=True, slots=True)
class FillOutcome:
    client_order_id: str
    state: OrderState
    # 부분 취소가 미체결 수량을 줄인다. 다른 경로에서는 주문 수량 그대로다.
    quantity: int
    filled_quantity: int
    average_fill_price: Decimal | None
    changed: bool
    problem: ReconcileProblem | None


@dataclass(frozen=True, slots=True)
class SyncResult:
    outcomes: tuple[FillOutcome, ...]
    problems: tuple[tuple[str, ReconcileProblem], ...]


def _unchanged(order: OrderSnapshot, problem: ReconcileProblem | None) -> FillOutcome:
    return FillOutcome(
        client_order_id=order.client_order_id,
        state=order.state,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        average_fill_price=order.average_fill_price,
        changed=False,
        problem=problem,
    )


def _target_state(order: OrderSnapshot, fill: BrokerFill) -> OrderState:
    if fill.filled_quantity >= order.quantity:
        return OrderState.FILLED
    if fill.canceled:
        return OrderState.CANCELED
    if fill.filled_quantity > 0:
        return OrderState.PARTIALLY_FILLED
    if fill.rejected_quantity >= order.quantity:
        return OrderState.REJECTED
    return order.state


def _problem(order: OrderSnapshot, fill: BrokerFill) -> ReconcileProblem | None:
    if fill.symbol != order.symbol:
        return ReconcileProblem.SYMBOL_MISMATCH
    if order.state in _TERMINAL_STATES and fill.filled_quantity != order.filled_quantity:
        return ReconcileProblem.TERMINAL_STATE_CHANGED
    if fill.filled_quantity > order.quantity:
        return ReconcileProblem.FILL_EXCEEDS_ORDER
    if fill.filled_quantity < order.filled_quantity:
        return ReconcileProblem.FILL_DECREASED
    return None


def _outcome(order: OrderSnapshot, fill: BrokerFill) -> FillOutcome:
    problem = _problem(order, fill)
    if problem is not None:
        return _unchanged(order, problem)
    state = _target_state(order, fill)
    changed = state is not order.state or fill.filled_quantity != order.filled_quantity
    if not changed:
        return _unchanged(order, None)
    return FillOutcome(
        client_order_id=order.client_order_id,
        state=state,
        # 일별주문체결 대조는 수량을 바꾸지 않는다. 부분 취소는 통보 경로만 다룬다.
        quantity=order.quantity,
        filled_quantity=fill.filled_quantity,
        average_fill_price=fill.average_fill_price or order.average_fill_price,
        changed=True,
        problem=None,
    )


def synchronize(
    orders: Iterable[OrderSnapshot],
    fills: Iterable[BrokerFill],
) -> SyncResult:
    """증권사 주문번호로 맞춘 뒤 상태 전이 목표와 불일치를 계산한다."""
    submitted = {order.broker_order_id: order for order in orders if order.broker_order_id}
    outcomes: list[FillOutcome] = []
    problems: list[tuple[str, ReconcileProblem]] = []
    matched: set[str] = set()
    for fill in fills:
        order = submitted.get(fill.broker_order_id)
        if order is None:
            problems.append((fill.broker_order_id, ReconcileProblem.UNKNOWN_BROKER_ORDER))
            continue
        matched.add(fill.broker_order_id)
        outcome = _outcome(order, fill)
        if outcome.problem is not None:
            problems.append((fill.broker_order_id, outcome.problem))
        outcomes.append(outcome)
    for broker_order_id, order in submitted.items():
        if broker_order_id not in matched:
            outcomes.append(_unchanged(order, None))
    return SyncResult(outcomes=tuple(outcomes), problems=tuple(problems))
