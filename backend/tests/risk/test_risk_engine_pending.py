from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide
from auto_stock_trading.domain.risk.engine import (
    AccountState,
    MarketQuote,
    PendingExposure,
    PlanRequest,
    SessionCounters,
    SignalCandidate,
    evaluate_plan,
)
from auto_stock_trading.domain.risk.limits import PAPER_RISK_LIMITS, RiskRule

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_NOW: Final = datetime.combine(datetime(2026, 8, 19, tzinfo=UTC).date(), time(10, 0), _SEOUL)
_NAV: Final = Decimal(10_000_000)
_PRICE: Final = Decimal(250_000)
_SYMBOL: Final = "005930"
_OTHER: Final = "069500"

_ACCOUNT: Final = AccountState(
    nav=_NAV,
    settled_cash=_NAV,
    orderable_cash=_NAV,
    session_open_nav=_NAV,
    peak_nav=_NAV,
    positions=(),
    reconciled=True,
)
_QUOTE: Final = MarketQuote(
    symbol=_SYMBOL,
    product_type=ProductType.STOCK,
    price=_PRICE,
    received_at=_NOW - timedelta(seconds=1),
    trading_status="active",
    sector=None,
)
_OTHER_QUOTE: Final = replace(
    _QUOTE,
    symbol=_OTHER,
    product_type=ProductType.ETF,
    price=Decimal(100_000),
)
_COUNTERS: Final = SessionCounters(
    open_orders=0,
    daily_order_attempts=0,
    daily_buy_amount=Decimal(0),
    consecutive_rejects=0,
    api_failures=0,
)


def _request(
    *,
    symbol: str,
    pending: tuple[PendingExposure, ...],
    counters: SessionCounters = _COUNTERS,
) -> PlanRequest:
    return PlanRequest(
        candidates=(SignalCandidate(symbol, OrderSide.BUY),),
        account=_ACCOUNT,
        quotes=(_QUOTE, _OTHER_QUOTE),
        counters=counters,
        automation_state=AutomationState.RUNNING,
        trading_day=True,
        now=_NOW,
        limits=PAPER_RISK_LIMITS,
        pending=pending,
    )


def test_a_fully_consumed_cap_leaves_no_room_rather_than_rejecting() -> None:
    """자리가 0이면 거절이 아니다(ADR-0020 결정 1).

    거절로 세면 통과할 수 없는 후보가 사흘이면 자동매매를 멈춘다(2026-09-01 실측). 시도가 막힌 것과
    애초에 넣을 자리가 없는 것은 다른 사실이다.
    """
    cap = _NAV * PAPER_RISK_LIMITS.unclassified_exposure
    pending = (PendingExposure(symbol=_SYMBOL, amount=cap),)

    evaluation = evaluate_plan(_request(symbol=_OTHER, pending=pending))

    assert evaluation.block_code is None
    assert evaluation.orders == ()
    (entry,) = evaluation.no_capacity
    assert entry.symbol == _OTHER
    assert entry.rule is RiskRule.UNCLASSIFIED_EXPOSURE
    assert entry.limit_value == cap


def test_room_too_small_for_one_share_is_also_no_capacity() -> None:
    """잔여가 0이 아니어도 한 주를 못 사면 넣을 자리가 없는 것이다(2026-09-01 실측).

    실제로 막힌 상황이 이 모양이었다 — 미분류 잔여 37,787원, 한 주 177,885원. `available <= 0`으로
    적으면 이 경우를 놓치고 거절이 계속 쌓인다.
    """
    cap = _NAV * PAPER_RISK_LIMITS.unclassified_exposure
    # 후보 한 주 값보다 작은 자리만 남긴다.
    pending = (PendingExposure(symbol=_SYMBOL, amount=cap - _OTHER_QUOTE.price + 1),)

    evaluation = evaluate_plan(_request(symbol=_OTHER, pending=pending))

    assert evaluation.orders == ()
    (entry,) = evaluation.no_capacity
    assert entry.rule is RiskRule.UNCLASSIFIED_EXPOSURE


def test_pending_orders_of_the_same_symbol_consume_the_symbol_cap() -> None:
    """종목 한도가 다 찼으면 자리가 없는 것이다(ADR-0020). 거절이 아니다."""
    pending = (PendingExposure(symbol=_SYMBOL, amount=_NAV * PAPER_RISK_LIMITS.symbol_exposure),)

    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=pending))

    assert evaluation.orders == ()
    (entry,) = evaluation.no_capacity
    assert entry.rule is RiskRule.SYMBOL_EXPOSURE


def test_partial_pending_exposure_leaves_room_for_the_remainder() -> None:
    pending = (PendingExposure(symbol=_SYMBOL, amount=Decimal(500_000)),)

    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=pending))

    assert [order.quantity for order in evaluation.orders] == [2]
    assert all(order.reject_code is None for order in evaluation.orders)


def test_pending_exposure_also_counts_towards_total_exposure() -> None:
    pending = (PendingExposure(symbol=_SYMBOL, amount=_NAV * PAPER_RISK_LIMITS.total_exposure),)

    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=pending))

    assert evaluation.orders == ()
    assert evaluation.no_capacity != ()


def test_no_pending_exposure_keeps_the_previous_behaviour() -> None:
    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=()))

    assert [order.quantity for order in evaluation.orders] == [2, 2]
