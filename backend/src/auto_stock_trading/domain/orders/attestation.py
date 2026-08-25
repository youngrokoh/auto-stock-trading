"""사람이 확인한 대조 종결의 순수 판정(ADR-0010). 값을 만들지 않고 어긋나면 거부한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.orders.models import (
    InvalidTransitionError,
    OrderState,
    next_order_state,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from auto_stock_trading.domain.orders.fills import OrderSnapshot

_OPEN_STATES: Final = frozenset({OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED})
# ADR-0010 결정 2의 허용 목표 상태. 거절은 제출 응답으로 이미 기록되므로 제외한다.
# `expired`는 ADR-0017이 상태를 만든 뒤 더했다 — 장이 끝나 체결되지 않은 주문을 `canceled`로 적으면
# 우리가 취소했다고 적는 것이므로 사실이 아니다. 사람 확인 경로도 사실대로 적을 수 있어야 한다.
_ALLOWED_STATES: Final = frozenset(
    {
        OrderState.FILLED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCELED,
        OrderState.EXPIRED,
    }
)


class AttestationReason(StrEnum):
    """거부 사유. 화면·감사·CLI가 같은 문자열을 쓴다."""

    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    NO_LISTENER_HISTORY = "NO_LISTENER_HISTORY"
    LISTENER_COVERED = "LISTENER_COVERED"
    NOT_OPEN = "NOT_OPEN"
    STATE_NOT_ALLOWED = "STATE_NOT_ALLOWED"
    TRANSITION_NOT_ALLOWED = "TRANSITION_NOT_ALLOWED"
    QUANTITY_EXCEEDS_ORDER = "QUANTITY_EXCEEDS_ORDER"
    QUANTITY_DECREASED = "QUANTITY_DECREASED"
    QUANTITY_NOT_COMPLETE = "QUANTITY_NOT_COMPLETE"
    QUANTITY_NOT_PARTIAL = "QUANTITY_NOT_PARTIAL"
    PRICE_REQUIRED = "PRICE_REQUIRED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"


@dataclass(frozen=True, slots=True)
class AttestationRequest:
    """사람이 KIS 화면에서 읽어 넣는 값. 시스템이 추정하지 않는다."""

    state: OrderState
    filled_quantity: int
    average_fill_price: Decimal | None
    operator: str
    evidence: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AttestationOutcome:
    client_order_id: str
    state: OrderState
    filled_quantity: int
    average_fill_price: Decimal | None
    operator: str
    evidence: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AttestationRejection:
    reason: AttestationReason


def _not_partial(order: OrderSnapshot, request: AttestationRequest) -> bool:
    """전량이 아닌 상태의 수량 규칙. 부분체결은 0 초과, 만료는 전량 미달이어야 한다.

    전량이 체결됐다면 만료가 아니다 — 모순된 조합을 사실로 받아들이지 않는다.
    """
    quantity = request.filled_quantity
    if request.state is OrderState.PARTIALLY_FILLED:
        return not 0 < quantity < order.quantity
    if request.state is OrderState.EXPIRED:
        return quantity >= order.quantity
    return False


def _quantity_reason(
    order: OrderSnapshot,
    request: AttestationRequest,
) -> AttestationReason | None:
    quantity = request.filled_quantity
    if quantity > order.quantity:
        return AttestationReason.QUANTITY_EXCEEDS_ORDER
    if quantity < order.filled_quantity:
        return AttestationReason.QUANTITY_DECREASED
    if request.state is OrderState.FILLED and quantity != order.quantity:
        return AttestationReason.QUANTITY_NOT_COMPLETE
    if _not_partial(order, request):
        return AttestationReason.QUANTITY_NOT_PARTIAL
    price = request.average_fill_price
    if quantity > 0 and (price is None or price <= 0):
        return AttestationReason.PRICE_REQUIRED
    return None


def _reason(order: OrderSnapshot, request: AttestationRequest) -> AttestationReason | None:
    if not request.operator.strip() or not request.evidence.strip():
        return AttestationReason.EVIDENCE_REQUIRED
    if order.state not in _OPEN_STATES:
        return AttestationReason.NOT_OPEN
    if request.state not in _ALLOWED_STATES:
        return AttestationReason.STATE_NOT_ALLOWED
    try:
        _ = next_order_state(order.state, request.state)
    except InvalidTransitionError:
        return AttestationReason.TRANSITION_NOT_ALLOWED
    return _quantity_reason(order, request)


def attest_order(
    order: OrderSnapshot,
    request: AttestationRequest,
) -> AttestationOutcome | AttestationRejection:
    """사람이 확인한 사실을 주문 상태 전이로 바꾼다. 근거가 없으면 거부한다."""
    reason = _reason(order, request)
    if reason is not None:
        return AttestationRejection(reason=reason)
    price = request.average_fill_price if request.filled_quantity > 0 else None
    return AttestationOutcome(
        client_order_id=order.client_order_id,
        state=request.state,
        filled_quantity=request.filled_quantity,
        average_fill_price=price,
        operator=request.operator,
        evidence=request.evidence,
        occurred_at=request.occurred_at,
    )
