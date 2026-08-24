"""실시간 체결통보 본문의 순수 해석. 값을 추정하지 않고 형식 위반은 fail-closed다."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final, override

from auto_stock_trading.domain.orders.fills import (
    FillOutcome,
    OrderSnapshot,
    ReconcileProblem,
)
from auto_stock_trading.domain.orders.models import OrderSide, OrderState

_SEPARATOR: Final = "^"
_MASK: Final = "***"
# 실시간 체결통보 계약의 필드 표. 인덱스는 계약과 같은 순서다.
_FIELD_COUNT: Final = 23
_CUSTOMER_ID: Final = 0
_ACCOUNT_NUMBER: Final = 1
_BROKER_ORDER_ID: Final = 2
_ORIGINAL_BROKER_ORDER_ID: Final = 3
_SIDE: Final = 4
_REVISE_CODE: Final = 5
_ORDER_KIND: Final = 6
_ORDER_CONDITION: Final = 7
_SYMBOL: Final = 8
_QUANTITY: Final = 9
_PRICE: Final = 10
_EVENT_TIME: Final = 11
_REJECTED: Final = 12
_KIND: Final = 13
_ACCEPT_CODE: Final = 14
_BRANCH_NO: Final = 15
_ORDER_QUANTITY: Final = 16
_ACCOUNT_NAME: Final = 17
_MASKED_FIELDS: Final = (_CUSTOMER_ID, _ACCOUNT_NUMBER, _ACCOUNT_NAME)

_SIDES: Final = {"01": OrderSide.SELL, "02": OrderSide.BUY}
_REJECTED_FLAG: Final = "1"
# 실측(2026-08-20): 취소 확인 통보는 정정구분 `2`, 접수여부 `2`로 오고 자체 주문번호를 받는다.
_REVISE_CANCEL: Final = "2"
_ACCEPT_CONFIRMED: Final = "2"
_TERMINAL_STATES: Final = frozenset({OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELED})


class NotificationKind(StrEnum):
    """체결여부(`CNTG_YN`). 주문·정정·취소·거부 통보와 체결 통보를 구분한다."""

    ORDER = "order"
    EXECUTION = "execution"


_KINDS: Final = {"1": NotificationKind.ORDER, "2": NotificationKind.EXECUTION}


@dataclass(frozen=True, slots=True)
class NotificationFormatError(Exception):
    """계약과 다른 본문. 체결을 놓쳤을 수 있으므로 추정하지 않고 실패로 남긴다."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"fill notification does not match the contract: {self.detail}"


@dataclass(frozen=True, slots=True)
class FillNotification:
    """체결통보 한 건의 증권사 사실. 개인정보 필드는 담지 않는다."""

    broker_order_id: str
    original_broker_order_id: str
    symbol: str
    side: OrderSide
    kind: NotificationKind
    quantity: int
    price: Decimal
    order_quantity: int
    broker_event_time: str
    rejected: bool
    revise_code: str
    accept_code: str
    order_kind: str
    order_condition: str
    branch_no: str

    @property
    def cancel_confirmed(self) -> bool:
        """취소 확인 통보. 정정 확인은 목표 포지션 재계산 규칙이 없어 포함하지 않는다."""
        return (
            self.kind is NotificationKind.ORDER
            and self.revise_code == _REVISE_CANCEL
            and self.accept_code == _ACCEPT_CONFIRMED
        )

    @property
    def matched_broker_order_id(self) -> str:
        """대조 키. 취소·정정 통보는 자체 주문번호를 받으므로 원주문번호로 맞춘다."""
        if self.original_broker_order_id and self.revise_code != "0":
            return self.original_broker_order_id
        return self.broker_order_id


def _records(payload: str) -> tuple[tuple[str, ...], ...]:
    fields = payload.split(_SEPARATOR)
    if len(fields) % _FIELD_COUNT != 0:
        detail = f"{len(fields)} fields are not a multiple of {_FIELD_COUNT}"
        raise NotificationFormatError(detail)
    return tuple(
        tuple(fields[start : start + _FIELD_COUNT]) for start in range(0, len(fields), _FIELD_COUNT)
    )


def _quantity(value: str, name: str) -> int:
    if not value.isdigit():
        detail = f"{name} is not a non-negative integer"
        raise NotificationFormatError(detail)
    return int(value)


def _price(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        detail = "price is not a decimal"
        raise NotificationFormatError(detail) from error


def _notification(record: tuple[str, ...]) -> FillNotification:
    side = _SIDES.get(record[_SIDE])
    if side is None:
        detail = "side code is unknown"
        raise NotificationFormatError(detail)
    kind = _KINDS.get(record[_KIND])
    if kind is None:
        detail = "execution flag is unknown"
        raise NotificationFormatError(detail)
    broker_order_id = record[_BROKER_ORDER_ID]
    if not broker_order_id:
        detail = "broker order id is empty"
        raise NotificationFormatError(detail)
    return FillNotification(
        broker_order_id=broker_order_id,
        original_broker_order_id=record[_ORIGINAL_BROKER_ORDER_ID],
        symbol=record[_SYMBOL],
        side=side,
        kind=kind,
        quantity=_quantity(record[_QUANTITY], "quantity"),
        price=_price(record[_PRICE]),
        order_quantity=_quantity(record[_ORDER_QUANTITY], "order quantity"),
        broker_event_time=record[_EVENT_TIME],
        rejected=record[_REJECTED] == _REJECTED_FLAG,
        revise_code=record[_REVISE_CODE],
        accept_code=record[_ACCEPT_CODE],
        order_kind=record[_ORDER_KIND],
        order_condition=record[_ORDER_CONDITION],
        branch_no=record[_BRANCH_NO],
    )


def parse_notifications(payload: str) -> tuple[FillNotification, ...]:
    """복호화된 본문을 통보 목록으로 만든다. 한 프레임에 여러 건이 올 수 있다."""
    return tuple(_notification(record) for record in _records(payload))


def mask_notification_payload(payload: str) -> str:
    """저장 전에 고객ID·계좌번호·계좌명을 지운다. 치환 전 문자열은 남기지 않는다."""
    records = _records(payload)
    masked: list[str] = []
    for record in records:
        fields = list(record)
        for index in _MASKED_FIELDS:
            fields[index] = _MASK
        masked.extend(fields)
    return _SEPARATOR.join(masked)


def _average_price(order: OrderSnapshot, notification: FillNotification) -> Decimal:
    filled = order.filled_quantity
    previous = order.average_fill_price
    if filled <= 0 or previous is None:
        return notification.price
    total = previous * filled + notification.price * notification.quantity
    return total / (filled + notification.quantity)


def _problem(
    order: OrderSnapshot,
    notification: FillNotification,
    accumulated: int,
) -> ReconcileProblem | None:
    if notification.symbol != order.symbol:
        return ReconcileProblem.SYMBOL_MISMATCH
    if not notification.cancel_confirmed and notification.order_quantity != order.quantity:
        return ReconcileProblem.ORDER_QUANTITY_MISMATCH
    if (
        notification.cancel_confirmed
        and notification.quantity > order.quantity - order.filled_quantity
    ):
        # 증권사가 초과 취소를 막지만(실측 40430000) 막지 못한 값이 오면 추측하지 않는다.
        return ReconcileProblem.ORDER_QUANTITY_MISMATCH
    if order.state in _TERMINAL_STATES:
        return ReconcileProblem.TERMINAL_STATE_CHANGED
    if accumulated > order.quantity:
        return ReconcileProblem.FILL_EXCEEDS_ORDER
    return None


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


def _cancelled(order: OrderSnapshot, notification: FillNotification) -> FillOutcome:
    """취소 확인을 **통보된 수량만큼** 반영한다(ADR-0013 결정 4).

    실측(2026-08-24): 통보는 취소된 수량을 싣는다. 카카오 14주 중 5주를 취소하면 통보 수량이 5이고
    9주가 증권사에 남는다. 통보 수량을 무시하고 전량 취소로 처리하면 내부는 취소됨·증권사는 열려
    있음이 되고, 비상정지가 그 주문을 대상에서 빼 미체결을 놓친다.

    수량 `0`은 **측정된 적이 없다.** 실측된 취소 통보는 모두 취소 수량을 실었다. 정보가 없는 값으로
    보고 종전 동작(전량 취소)을 유지한다 — 측정하지 않은 곳에서 동작을 바꾸지 않는다.
    """
    outstanding = order.quantity - order.filled_quantity
    cancelled = notification.quantity
    if cancelled == 0 or cancelled >= outstanding:
        return FillOutcome(
            client_order_id=order.client_order_id,
            state=OrderState.CANCELED,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
            changed=True,
            problem=None,
        )
    return FillOutcome(
        client_order_id=order.client_order_id,
        state=order.state,
        quantity=order.quantity - cancelled,
        filled_quantity=order.filled_quantity,
        average_fill_price=order.average_fill_price,
        changed=True,
        problem=None,
    )


def apply_notification(order: OrderSnapshot, notification: FillNotification) -> FillOutcome:
    """통보 한 건을 주문 상태에 반영한다. 누적은 직전 누적에 통보 수량을 더해 만든다."""
    accumulated = order.filled_quantity + (
        notification.quantity if notification.kind is NotificationKind.EXECUTION else 0
    )
    problem = _problem(order, notification, accumulated)
    if problem is not None:
        return _unchanged(order, problem)
    if notification.rejected:
        return FillOutcome(
            client_order_id=order.client_order_id,
            state=OrderState.REJECTED,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
            changed=True,
            problem=None,
        )
    if notification.cancel_confirmed:
        return _cancelled(order, notification)
    if notification.kind is not NotificationKind.EXECUTION or notification.quantity == 0:
        return _unchanged(order, None)
    state = OrderState.FILLED if accumulated == order.quantity else OrderState.PARTIALLY_FILLED
    return FillOutcome(
        client_order_id=order.client_order_id,
        state=state,
        quantity=order.quantity,
        filled_quantity=accumulated,
        average_fill_price=_average_price(order, notification),
        changed=True,
        problem=None,
    )
