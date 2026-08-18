from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    InvalidTransitionError,
    OrderIdentity,
    OrderSide,
    OrderState,
    client_order_id,
    next_automation_state,
    next_order_state,
)
from auto_stock_trading.domain.orders.pricing import (
    round_to_tick,
    tick_size,
    within_price_band,
)


def test_order_state_machine_follows_approved_graph() -> None:
    assert next_order_state(OrderState.PLANNED, OrderState.SUBMITTED) is OrderState.SUBMITTED
    assert next_order_state(OrderState.PLANNED, OrderState.REJECTED) is OrderState.REJECTED
    assert next_order_state(OrderState.PLANNED, OrderState.CANCELED) is OrderState.CANCELED
    assert (
        next_order_state(OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED)
        is OrderState.PARTIALLY_FILLED
    )
    assert (
        next_order_state(OrderState.PARTIALLY_FILLED, OrderState.PARTIALLY_FILLED)
        is OrderState.PARTIALLY_FILLED
    )
    assert next_order_state(OrderState.PARTIALLY_FILLED, OrderState.FILLED) is OrderState.FILLED


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (OrderState.PLANNED, OrderState.FILLED),
        (OrderState.PLANNED, OrderState.PARTIALLY_FILLED),
        (OrderState.FILLED, OrderState.CANCELED),
        (OrderState.REJECTED, OrderState.SUBMITTED),
        (OrderState.CANCELED, OrderState.SUBMITTED),
        (OrderState.SUBMITTED, OrderState.PLANNED),
    ],
)
def test_order_state_machine_rejects_other_transitions(
    current: OrderState,
    requested: OrderState,
) -> None:
    with pytest.raises(InvalidTransitionError):
        _ = next_order_state(current, requested)


def test_automation_state_machine_follows_policy_graph() -> None:
    assert (
        next_automation_state(AutomationState.DISABLED, AutomationState.ARMED)
        is AutomationState.ARMED
    )
    assert (
        next_automation_state(AutomationState.ARMED, AutomationState.RUNNING)
        is AutomationState.RUNNING
    )
    assert (
        next_automation_state(AutomationState.RUNNING, AutomationState.PAUSED)
        is AutomationState.PAUSED
    )
    assert (
        next_automation_state(AutomationState.PAUSED, AutomationState.ARMED)
        is AutomationState.ARMED
    )
    assert (
        next_automation_state(AutomationState.EMERGENCY_STOP, AutomationState.DISABLED)
        is AutomationState.DISABLED
    )
    for state in AutomationState:
        if state is AutomationState.EMERGENCY_STOP:
            continue
        assert (
            next_automation_state(state, AutomationState.EMERGENCY_STOP)
            is AutomationState.EMERGENCY_STOP
        )


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (AutomationState.DISABLED, AutomationState.RUNNING),
        (AutomationState.ARMED, AutomationState.ARMED),
        (AutomationState.PAUSED, AutomationState.RUNNING),
        (AutomationState.EMERGENCY_STOP, AutomationState.RUNNING),
        (AutomationState.EMERGENCY_STOP, AutomationState.ARMED),
    ],
)
def test_automation_state_machine_rejects_unsafe_transitions(
    current: AutomationState,
    requested: AutomationState,
) -> None:
    with pytest.raises(InvalidTransitionError):
        _ = next_automation_state(current, requested)


_SIGNAL_DATE: Final = date(2026, 8, 18)


def _identity(
    *,
    signal_date: date | None = None,
    side: OrderSide = OrderSide.BUY,
    sequence: int = 1,
) -> OrderIdentity:
    return OrderIdentity(
        strategy_name="ma-rsi",
        strategy_version="1",
        signal_date=signal_date or _SIGNAL_DATE,
        symbol="005930",
        side=side,
        sequence=sequence,
    )


def test_client_order_id_is_deterministic_and_signal_scoped() -> None:
    first = client_order_id(_identity())
    same = client_order_id(_identity())
    other_sequence = client_order_id(_identity(sequence=2))
    other_side = client_order_id(_identity(side=OrderSide.SELL))
    other_signal = client_order_id(_identity(signal_date=date(2026, 8, 17)))

    assert first == same
    assert len(first) == 32
    assert len({first, other_sequence, other_side, other_signal}) == 4


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (Decimal(1999), Decimal(1)),
        (Decimal(2000), Decimal(5)),
        (Decimal(4999), Decimal(5)),
        (Decimal(5000), Decimal(10)),
        (Decimal(19999), Decimal(10)),
        (Decimal(20000), Decimal(50)),
        (Decimal(49999), Decimal(50)),
        (Decimal(50000), Decimal(100)),
        (Decimal(199999), Decimal(100)),
        (Decimal(200000), Decimal(500)),
        (Decimal(499999), Decimal(500)),
        (Decimal(500000), Decimal(1000)),
    ],
)
def test_stock_tick_size_follows_krx_bands(price: Decimal, expected: Decimal) -> None:
    assert tick_size(price, ProductType.STOCK) == expected


def test_etf_tick_size_is_five_won_regardless_of_price() -> None:
    assert tick_size(Decimal(1000), ProductType.ETF) == Decimal(5)
    assert tick_size(Decimal(600000), ProductType.ETF) == Decimal(5)


def test_round_to_tick_uses_nearest_tick() -> None:
    assert round_to_tick(Decimal(274512), ProductType.STOCK) == Decimal(274500)
    assert round_to_tick(Decimal(274750), ProductType.STOCK) == Decimal(275000)
    assert round_to_tick(Decimal(110063), ProductType.ETF) == Decimal(110065)


def test_price_band_allows_one_percent_and_rejects_beyond() -> None:
    reference = Decimal(100000)
    assert within_price_band(OrderSide.BUY, Decimal(101000), reference)
    assert not within_price_band(OrderSide.BUY, Decimal(101001), reference)
    assert within_price_band(OrderSide.SELL, Decimal(99000), reference)
    assert not within_price_band(OrderSide.SELL, Decimal(98999), reference)
