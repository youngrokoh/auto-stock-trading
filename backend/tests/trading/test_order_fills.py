from dataclasses import replace
from decimal import Decimal
from typing import Final

from auto_stock_trading.domain.orders.fills import (
    BrokerFill,
    OrderSnapshot,
    ReconcileProblem,
    synchronize,
)
from auto_stock_trading.domain.orders.models import OrderState

_PRICE: Final = Decimal("71800.00000000")
_ORDER: Final = OrderSnapshot(
    client_order_id="a" * 32,
    broker_order_id="0000117057",
    symbol="005930",
    quantity=3,
    filled_quantity=0,
    average_fill_price=None,
    state=OrderState.SUBMITTED,
)
_FILL: Final = BrokerFill(
    broker_order_id="0000117057",
    symbol="005930",
    order_quantity=3,
    filled_quantity=0,
    remaining_quantity=3,
    rejected_quantity=0,
    canceled=False,
    average_fill_price=None,
)


def test_unfilled_submitted_order_keeps_its_state() -> None:
    result = synchronize((_ORDER,), (_FILL,))

    (outcome,) = result.outcomes
    assert outcome.state is OrderState.SUBMITTED
    assert outcome.changed is False
    assert outcome.filled_quantity == 0
    assert result.problems == ()


def test_partial_fill_moves_to_partially_filled_with_broker_values() -> None:
    fill = replace(
        _FILL,
        filled_quantity=1,
        remaining_quantity=2,
        average_fill_price=_PRICE,
    )

    (outcome,) = synchronize((_ORDER,), (fill,)).outcomes

    assert outcome.state is OrderState.PARTIALLY_FILLED
    assert outcome.changed is True
    assert outcome.filled_quantity == 1
    assert outcome.average_fill_price == _PRICE


def test_full_fill_moves_to_filled() -> None:
    fill = replace(_FILL, filled_quantity=3, remaining_quantity=0, average_fill_price=_PRICE)

    (outcome,) = synchronize((_ORDER,), (fill,)).outcomes

    assert outcome.state is OrderState.FILLED
    assert outcome.filled_quantity == 3


def test_additional_fill_on_partially_filled_order_updates_quantity() -> None:
    order = replace(
        _ORDER,
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=1,
        average_fill_price=_PRICE,
    )
    fill = replace(_FILL, filled_quantity=2, remaining_quantity=1, average_fill_price=_PRICE)

    (outcome,) = synchronize((order,), (fill,)).outcomes

    assert outcome.state is OrderState.PARTIALLY_FILLED
    assert outcome.changed is True
    assert outcome.filled_quantity == 2


def test_cancelled_unfilled_order_moves_to_canceled() -> None:
    fill = replace(_FILL, canceled=True, remaining_quantity=0)

    (outcome,) = synchronize((_ORDER,), (fill,)).outcomes

    assert outcome.state is OrderState.CANCELED
    assert outcome.filled_quantity == 0


def test_cancelled_partially_filled_order_keeps_the_filled_quantity() -> None:
    fill = replace(
        _FILL,
        filled_quantity=1,
        remaining_quantity=0,
        canceled=True,
        average_fill_price=_PRICE,
    )

    (outcome,) = synchronize((_ORDER,), (fill,)).outcomes

    assert outcome.state is OrderState.CANCELED
    assert outcome.filled_quantity == 1
    assert outcome.average_fill_price == _PRICE


def test_fully_rejected_order_moves_to_rejected() -> None:
    fill = replace(_FILL, rejected_quantity=3, remaining_quantity=0)

    (outcome,) = synchronize((_ORDER,), (fill,)).outcomes

    assert outcome.state is OrderState.REJECTED
    assert outcome.filled_quantity == 0


def test_broker_order_without_internal_order_is_a_reconcile_problem() -> None:
    fill = replace(_FILL, broker_order_id="0000999999")

    result = synchronize((_ORDER,), (fill,))

    assert result.problems == (("0000999999", ReconcileProblem.UNKNOWN_BROKER_ORDER),)
    assert [outcome.changed for outcome in result.outcomes] == [False]


def test_fill_above_order_quantity_is_a_reconcile_problem() -> None:
    fill = replace(_FILL, filled_quantity=4, remaining_quantity=0, average_fill_price=_PRICE)

    result = synchronize((_ORDER,), (fill,))

    assert result.problems == (("0000117057", ReconcileProblem.FILL_EXCEEDS_ORDER),)
    assert result.outcomes[0].changed is False


def test_decreasing_fill_quantity_is_a_reconcile_problem() -> None:
    order = replace(
        _ORDER,
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=2,
        average_fill_price=_PRICE,
    )
    fill = replace(_FILL, filled_quantity=1, remaining_quantity=2, average_fill_price=_PRICE)

    result = synchronize((order,), (fill,))

    assert result.problems == (("0000117057", ReconcileProblem.FILL_DECREASED),)


def test_changed_fill_on_terminal_order_is_a_reconcile_problem() -> None:
    order = replace(
        _ORDER,
        state=OrderState.FILLED,
        filled_quantity=3,
        average_fill_price=_PRICE,
    )
    fill = replace(_FILL, filled_quantity=2, remaining_quantity=1, average_fill_price=_PRICE)

    result = synchronize((order,), (fill,))

    assert result.problems == (("0000117057", ReconcileProblem.TERMINAL_STATE_CHANGED),)


def test_terminal_order_with_matching_fill_is_not_a_problem() -> None:
    order = replace(
        _ORDER,
        state=OrderState.FILLED,
        filled_quantity=3,
        average_fill_price=_PRICE,
    )
    fill = replace(_FILL, filled_quantity=3, remaining_quantity=0, average_fill_price=_PRICE)

    result = synchronize((order,), (fill,))

    assert result.problems == ()
    assert result.outcomes[0].changed is False


def test_orders_without_broker_id_are_left_untouched() -> None:
    order = replace(_ORDER, broker_order_id=None, state=OrderState.PLANNED)

    result = synchronize((order,), ())

    assert result.problems == ()
    assert result.outcomes == ()


def test_symbol_mismatch_on_matched_order_is_a_reconcile_problem() -> None:
    fill = replace(_FILL, symbol="069500", filled_quantity=1, average_fill_price=_PRICE)

    result = synchronize((_ORDER,), (fill,))

    assert result.problems == (("0000117057", ReconcileProblem.SYMBOL_MISMATCH),)
