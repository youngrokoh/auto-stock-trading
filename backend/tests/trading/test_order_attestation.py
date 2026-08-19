from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.orders.attestation import (
    AttestationRejection,
    AttestationRequest,
    attest_order,
)
from auto_stock_trading.domain.orders.fills import OrderSnapshot
from auto_stock_trading.domain.orders.models import OrderState

_NOW: Final = datetime(2026, 8, 19, 7, 10, tzinfo=UTC)
_OPERATOR: Final = "yroh1"
_EVIDENCE: Final = "KIS 모의투자 잔고화면 2026-08-19 16:10"
_DEFAULT_PRICE: Final = Decimal(248750)


def _order(
    *,
    quantity: int = 2,
    filled_quantity: int = 0,
    state: OrderState = OrderState.SUBMITTED,
) -> OrderSnapshot:
    return OrderSnapshot(
        client_order_id="fixture-client-order-id",
        broker_order_id="0000008637",
        symbol="005930",
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None,
        state=state,
    )


def _request(
    *,
    state: OrderState = OrderState.FILLED,
    quantity: int = 2,
    price: Decimal | None = _DEFAULT_PRICE,
) -> AttestationRequest:
    return AttestationRequest(
        state=state,
        filled_quantity=quantity,
        average_fill_price=price,
        operator=_OPERATOR,
        evidence=_EVIDENCE,
        occurred_at=_NOW,
    )


def test_full_fill_is_attested_with_the_operator_evidence() -> None:
    outcome = attest_order(_order(), _request())

    assert not isinstance(outcome, AttestationRejection)
    assert outcome.state is OrderState.FILLED
    assert outcome.filled_quantity == 2
    assert outcome.average_fill_price == Decimal(248750)
    assert outcome.operator == _OPERATOR
    assert outcome.evidence == _EVIDENCE


def test_partial_fill_is_attested() -> None:
    outcome = attest_order(
        _order(quantity=4),
        _request(state=OrderState.PARTIALLY_FILLED, quantity=3),
    )

    assert not isinstance(outcome, AttestationRejection)
    assert outcome.state is OrderState.PARTIALLY_FILLED
    assert outcome.filled_quantity == 3


def test_cancellation_without_any_fill_needs_no_price() -> None:
    outcome = attest_order(
        _order(),
        _request(state=OrderState.CANCELED, quantity=0, price=None),
    )

    assert not isinstance(outcome, AttestationRejection)
    assert outcome.state is OrderState.CANCELED
    assert outcome.filled_quantity == 0
    assert outcome.average_fill_price is None


def test_cancellation_after_a_partial_fill_keeps_the_filled_quantity() -> None:
    outcome = attest_order(
        _order(quantity=4, filled_quantity=1, state=OrderState.PARTIALLY_FILLED),
        _request(state=OrderState.CANCELED, quantity=1, price=Decimal(248750)),
    )

    assert not isinstance(outcome, AttestationRejection)
    assert outcome.filled_quantity == 1


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (OrderState.PLANNED, "NOT_OPEN"),
        (OrderState.FILLED, "NOT_OPEN"),
        (OrderState.REJECTED, "NOT_OPEN"),
        (OrderState.CANCELED, "NOT_OPEN"),
    ],
)
def test_orders_that_are_not_open_are_rejected(state: OrderState, reason: str) -> None:
    outcome = attest_order(_order(state=state), _request())

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == reason


@pytest.mark.parametrize(
    "state",
    [OrderState.PLANNED, OrderState.SUBMITTED, OrderState.REJECTED],
)
def test_target_states_outside_the_approved_set_are_rejected(state: OrderState) -> None:
    outcome = attest_order(_order(), _request(state=state))

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == "STATE_NOT_ALLOWED"


@pytest.mark.parametrize(
    ("order_quantity", "request_quantity", "state", "reason"),
    [
        (2, 3, OrderState.FILLED, "QUANTITY_EXCEEDS_ORDER"),
        (2, 2, OrderState.PARTIALLY_FILLED, "QUANTITY_NOT_PARTIAL"),
        (4, 0, OrderState.PARTIALLY_FILLED, "QUANTITY_NOT_PARTIAL"),
        (4, 3, OrderState.FILLED, "QUANTITY_NOT_COMPLETE"),
    ],
)
def test_quantity_rules_are_enforced(
    order_quantity: int,
    request_quantity: int,
    state: OrderState,
    reason: str,
) -> None:
    outcome = attest_order(
        _order(quantity=order_quantity),
        _request(state=state, quantity=request_quantity),
    )

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == reason


def test_a_decreasing_filled_quantity_is_rejected() -> None:
    outcome = attest_order(
        _order(quantity=4, filled_quantity=3, state=OrderState.PARTIALLY_FILLED),
        _request(state=OrderState.CANCELED, quantity=2),
    )

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == "QUANTITY_DECREASED"


@pytest.mark.parametrize("price", [None, Decimal(0), Decimal(-1)])
def test_a_fill_without_a_positive_price_is_rejected(price: Decimal | None) -> None:
    outcome = attest_order(_order(), _request(price=price))

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == "PRICE_REQUIRED"


@pytest.mark.parametrize(("operator", "evidence"), [("", _EVIDENCE), (_OPERATOR, "   ")])
def test_missing_operator_or_evidence_is_rejected(operator: str, evidence: str) -> None:
    request = AttestationRequest(
        state=OrderState.FILLED,
        filled_quantity=2,
        average_fill_price=Decimal(248750),
        operator=operator,
        evidence=evidence,
        occurred_at=_NOW,
    )

    outcome = attest_order(_order(), request)

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == "EVIDENCE_REQUIRED"


def test_a_transition_the_state_graph_forbids_is_rejected() -> None:
    outcome = attest_order(
        _order(quantity=4, filled_quantity=2, state=OrderState.PARTIALLY_FILLED),
        _request(state=OrderState.PARTIALLY_FILLED, quantity=3),
    )

    assert not isinstance(outcome, AttestationRejection)


def test_partially_filled_cannot_be_attested_as_rejected() -> None:
    outcome = attest_order(
        _order(quantity=4, filled_quantity=2, state=OrderState.PARTIALLY_FILLED),
        _request(state=OrderState.REJECTED, quantity=2),
    )

    assert isinstance(outcome, AttestationRejection)
    assert outcome.reason.value == "STATE_NOT_ALLOWED"
