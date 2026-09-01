from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide
from auto_stock_trading.domain.risk.engine import (
    AccountState,
    MarketQuote,
    PlanRequest,
    PositionState,
    SessionCounters,
    SignalCandidate,
    evaluate_plan,
)
from auto_stock_trading.domain.risk.limits import PAPER_RISK_LIMITS, BlockCode, RiskRule

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TRADING_DATE: Final = datetime(2026, 8, 18, tzinfo=UTC).date()
_NOW: Final = datetime.combine(_TRADING_DATE, time(10, 0), _SEOUL)
_NAV: Final = Decimal(100_000_000)
_PRICE: Final = Decimal(100_000)
_SYMBOL: Final = "005930"
_OTHER: Final = "069500"

_QUOTE: Final = MarketQuote(
    symbol=_SYMBOL,
    product_type=ProductType.STOCK,
    price=_PRICE,
    received_at=_NOW - timedelta(seconds=1),
    trading_status="active",
    sector=None,
)
_ETF_QUOTE: Final = replace(_QUOTE, symbol=_OTHER, product_type=ProductType.ETF)
_ACCOUNT: Final = AccountState(
    nav=_NAV,
    settled_cash=_NAV,
    orderable_cash=_NAV,
    session_open_nav=_NAV,
    peak_nav=_NAV,
    positions=(),
    reconciled=True,
)
_COUNTERS: Final = SessionCounters(
    open_orders=0,
    daily_order_attempts=0,
    daily_buy_amount=Decimal(0),
    consecutive_rejects=0,
    api_failures=0,
)
_REQUEST: Final = PlanRequest(
    candidates=(SignalCandidate(_SYMBOL, OrderSide.BUY),),
    account=_ACCOUNT,
    quotes=(_QUOTE,),
    counters=_COUNTERS,
    automation_state=AutomationState.RUNNING,
    trading_day=True,
    now=_NOW,
    limits=PAPER_RISK_LIMITS,
)


def _position(
    *,
    symbol: str = _SYMBOL,
    quantity: int,
    orderable_quantity: int | None = None,
) -> PositionState:
    return PositionState(
        symbol=symbol,
        quantity=quantity,
        orderable_quantity=quantity if orderable_quantity is None else orderable_quantity,
        evaluation_amount=_PRICE * quantity,
    )


def test_buy_target_uses_symbol_limit_and_splits_by_order_limit() -> None:
    evaluation = evaluate_plan(_REQUEST)

    assert evaluation.block_code is None
    assert evaluation.pause_rule is None
    assert [(order.sequence, order.quantity, order.limit_price) for order in evaluation.orders] == [
        (1, 50, _PRICE),
        (2, 50, _PRICE),
    ]
    assert all(order.reject_code is None for order in evaluation.orders)
    assert all(order.side is OrderSide.BUY for order in evaluation.orders)
    first = evaluation.orders[0]
    assert {decision.rule for decision in first.decisions} == {
        RiskRule.SYMBOL_EXPOSURE,
        RiskRule.UNCLASSIFIED_EXPOSURE,
        RiskRule.TOTAL_EXPOSURE,
        RiskRule.MIN_CASH,
        RiskRule.ORDERABLE_CASH,
        RiskRule.DAILY_BUY_AMOUNT,
        RiskRule.ORDER_AMOUNT,
        RiskRule.OPEN_ORDERS,
        RiskRule.ORDER_PRICE_BAND,
    }
    assert all(decision.passed for decision in first.decisions)


def test_evaluation_is_deterministic_for_identical_input() -> None:
    assert evaluate_plan(_REQUEST) == evaluate_plan(_REQUEST)


@pytest.mark.parametrize(
    "state",
    [
        AutomationState.DISABLED,
        AutomationState.ARMED,
        AutomationState.PAUSED,
        AutomationState.EMERGENCY_STOP,
    ],
)
def test_automation_state_must_be_running(state: AutomationState) -> None:
    evaluation = evaluate_plan(replace(_REQUEST, automation_state=state))

    assert evaluation.orders == ()
    assert evaluation.block_code == BlockCode.AUTOMATION_NOT_RUNNING


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        (time(9, 4), BlockCode.MARKET_CLOSED.value),
        (time(9, 5), None),
        (time(15, 15), None),
        (time(15, 16), BlockCode.MARKET_CLOSED.value),
    ],
)
def test_order_window_boundaries_follow_policy(clock: time, expected: str | None) -> None:
    now = datetime.combine(_TRADING_DATE, clock, _SEOUL)
    request = replace(
        _REQUEST,
        now=now,
        quotes=(replace(_QUOTE, received_at=now - timedelta(seconds=1)),),
    )

    assert evaluate_plan(request).block_code == expected


def test_non_trading_day_is_blocked() -> None:
    evaluation = evaluate_plan(replace(_REQUEST, trading_day=False))

    assert evaluation.block_code == BlockCode.MARKET_CLOSED


def test_unreconciled_account_is_blocked() -> None:
    evaluation = evaluate_plan(
        replace(_REQUEST, account=replace(_ACCOUNT, reconciled=False)),
    )

    assert evaluation.orders == ()
    assert evaluation.block_code == BlockCode.ACCOUNT_NOT_RECONCILED


def test_consecutive_api_failures_block_and_pause() -> None:
    evaluation = evaluate_plan(
        replace(_REQUEST, counters=replace(_COUNTERS, api_failures=3)),
    )

    assert evaluation.block_code == BlockCode.API_CONSECUTIVE_FAILURE
    assert evaluation.pause_rule is RiskRule.API_FAILURES


@pytest.mark.parametrize(
    ("nav", "expected"),
    [
        (Decimal(98_010_000), None),
        (Decimal(98_000_000), RiskRule.DAILY_LOSS),
        (Decimal(97_990_000), RiskRule.DAILY_LOSS),
    ],
)
def test_daily_loss_limit_boundaries(nav: Decimal, expected: RiskRule | None) -> None:
    account = replace(_ACCOUNT, nav=nav, session_open_nav=_NAV, peak_nav=nav)

    assert evaluate_plan(replace(_REQUEST, account=account)).pause_rule is expected


@pytest.mark.parametrize(
    ("nav", "expected"),
    [
        (Decimal(95_010_000), None),
        (Decimal(95_000_000), RiskRule.DRAWDOWN),
        (Decimal(94_990_000), RiskRule.DRAWDOWN),
    ],
)
def test_drawdown_limit_boundaries(nav: Decimal, expected: RiskRule | None) -> None:
    account = replace(_ACCOUNT, nav=nav, session_open_nav=nav, peak_nav=_NAV)

    assert evaluate_plan(replace(_REQUEST, account=account)).pause_rule is expected


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [(19, None), (20, RiskRule.DAILY_ORDER_ATTEMPTS), (21, RiskRule.DAILY_ORDER_ATTEMPTS)],
)
def test_daily_order_attempt_limit_boundaries(attempts: int, expected: RiskRule | None) -> None:
    counters = replace(_COUNTERS, daily_order_attempts=attempts)

    assert evaluate_plan(replace(_REQUEST, counters=counters)).pause_rule is expected


@pytest.mark.parametrize(
    ("rejects", "expected"),
    [(2, None), (3, RiskRule.CONSECUTIVE_REJECTS), (4, RiskRule.CONSECUTIVE_REJECTS)],
)
def test_consecutive_reject_limit_boundaries(rejects: int, expected: RiskRule | None) -> None:
    counters = replace(_COUNTERS, consecutive_rejects=rejects)

    assert evaluate_plan(replace(_REQUEST, counters=counters)).pause_rule is expected


def test_stale_quote_rejects_only_that_candidate() -> None:
    stale = replace(_QUOTE, received_at=_NOW - timedelta(seconds=11))
    evaluation = evaluate_plan(replace(_REQUEST, quotes=(stale,)))

    (order,) = evaluation.orders
    assert order.reject_code == BlockCode.DATA_STALE
    assert order.quantity == 0


def test_quote_exactly_at_freshness_limit_is_accepted() -> None:
    fresh = replace(_QUOTE, received_at=_NOW - timedelta(seconds=10))
    evaluation = evaluate_plan(replace(_REQUEST, quotes=(fresh,)))

    assert all(order.reject_code is None for order in evaluation.orders)


def test_missing_quote_is_rejected_as_stale() -> None:
    evaluation = evaluate_plan(replace(_REQUEST, quotes=(_ETF_QUOTE,)))

    (order,) = evaluation.orders
    assert order.reject_code == BlockCode.DATA_STALE
    assert order.limit_price is None
    assert order.reference_price is None


def test_suspended_symbol_is_rejected() -> None:
    suspended = replace(_QUOTE, trading_status="suspended")
    evaluation = evaluate_plan(replace(_REQUEST, quotes=(suspended,)))

    (order,) = evaluation.orders
    assert order.reject_code == BlockCode.SYMBOL_SUSPENDED
    assert order.quantity == 0


def test_symbol_exposure_limit_caps_additional_quantity() -> None:
    account = replace(
        _ACCOUNT,
        settled_cash=Decimal(90_500_000),
        orderable_cash=Decimal(90_500_000),
        positions=(_position(quantity=95),),
    )

    (order,) = evaluate_plan(replace(_REQUEST, account=account)).orders

    assert order.quantity == 5
    assert order.reject_code is None


def test_symbol_exposure_limit_creates_no_order_when_target_is_met() -> None:
    account = replace(
        _ACCOUNT,
        settled_cash=Decimal(90_000_000),
        orderable_cash=Decimal(90_000_000),
        positions=(_position(quantity=100),),
    )

    assert evaluate_plan(replace(_REQUEST, account=account)).orders == ()


def test_unclassified_total_limit_blocks_the_second_symbol() -> None:
    request = replace(
        _REQUEST,
        candidates=(
            SignalCandidate(_SYMBOL, OrderSide.BUY),
            SignalCandidate(_OTHER, OrderSide.BUY),
        ),
        quotes=(_QUOTE, _ETF_QUOTE),
    )

    evaluation = evaluate_plan(request)

    # 첫 종목이 미분류 한도를 채우면 둘째는 넣을 자리가 없다 — 거절이 아니다(ADR-0020).
    assert [order.symbol for order in evaluation.orders] == [_SYMBOL, _SYMBOL]
    (entry,) = evaluation.no_capacity
    assert entry.symbol == _OTHER
    assert entry.rule is RiskRule.UNCLASSIFIED_EXPOSURE


def test_minimum_cash_limit_caps_additional_quantity() -> None:
    account = replace(_ACCOUNT, settled_cash=Decimal(25_000_000))

    (order,) = evaluate_plan(replace(_REQUEST, account=account)).orders

    assert order.quantity == 50
    min_cash = next(decision for decision in order.decisions if decision.rule is RiskRule.MIN_CASH)
    assert min_cash.limit_value == Decimal(20_000_000)
    assert min_cash.projected_value == Decimal(20_000_000)
    assert min_cash.passed


def test_orderable_cash_limit_caps_additional_quantity() -> None:
    account = replace(_ACCOUNT, orderable_cash=Decimal(3_000_000))

    (order,) = evaluate_plan(replace(_REQUEST, account=account)).orders

    assert order.quantity == 30


def test_daily_buy_amount_limit_caps_additional_quantity() -> None:
    counters = replace(_COUNTERS, daily_order_attempts=1, daily_buy_amount=Decimal(18_000_000))

    (order,) = evaluate_plan(replace(_REQUEST, counters=counters)).orders

    assert order.quantity == 20


def test_total_exposure_limit_caps_additional_quantity() -> None:
    account = replace(
        _ACCOUNT,
        settled_cash=Decimal(22_000_000),
        orderable_cash=Decimal(22_000_000),
        positions=(_position(symbol=_OTHER, quantity=780),),
    )
    request = replace(
        _REQUEST,
        account=account,
        quotes=(_QUOTE, replace(_ETF_QUOTE, sector="finance")),
    )

    (order,) = evaluate_plan(request).orders

    assert order.quantity == 20


def test_open_order_limit_reduces_created_orders() -> None:
    counters = replace(_COUNTERS, open_orders=4)

    evaluation = evaluate_plan(replace(_REQUEST, counters=counters))

    assert [order.quantity for order in evaluation.orders] == [50]


def test_open_order_limit_rejects_when_exhausted() -> None:
    counters = replace(_COUNTERS, open_orders=5)

    (order,) = evaluate_plan(replace(_REQUEST, counters=counters)).orders

    assert order.reject_code == RiskRule.OPEN_ORDERS
    assert order.quantity == 0


def test_sell_signal_liquidates_position_within_order_limit() -> None:
    account = replace(
        _ACCOUNT,
        settled_cash=Decimal(90_000_000),
        orderable_cash=Decimal(90_000_000),
        positions=(_position(quantity=100),),
    )
    request = replace(
        _REQUEST,
        candidates=(SignalCandidate(_SYMBOL, OrderSide.SELL),),
        account=account,
    )

    evaluation = evaluate_plan(request)

    assert [(order.side, order.quantity) for order in evaluation.orders] == [
        (OrderSide.SELL, 50),
        (OrderSide.SELL, 50),
    ]


def test_sell_quantity_is_capped_by_orderable_quantity() -> None:
    account = replace(
        _ACCOUNT,
        settled_cash=Decimal(90_000_000),
        orderable_cash=Decimal(90_000_000),
        positions=(_position(quantity=100, orderable_quantity=30),),
    )
    request = replace(
        _REQUEST,
        candidates=(SignalCandidate(_SYMBOL, OrderSide.SELL),),
        account=account,
    )

    assert [order.quantity for order in evaluate_plan(request).orders] == [30]


def test_sell_without_position_creates_no_order() -> None:
    request = replace(_REQUEST, candidates=(SignalCandidate(_SYMBOL, OrderSide.SELL),))

    assert evaluate_plan(request).orders == ()
