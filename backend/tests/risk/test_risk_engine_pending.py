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


def test_pending_orders_of_another_symbol_consume_the_unclassified_cap() -> None:
    """정책 §2: 미체결·계획 주문이 모두 체결된다고 가정한 예상 노출로 검사한다."""
    cap = _NAV * PAPER_RISK_LIMITS.unclassified_exposure
    pending = (PendingExposure(symbol=_SYMBOL, amount=cap),)

    evaluation = evaluate_plan(_request(symbol=_OTHER, pending=pending))

    assert evaluation.block_code is None
    (order,) = evaluation.orders
    assert order.quantity == 0
    assert order.reject_code == RiskRule.UNCLASSIFIED_EXPOSURE.value


def test_pending_orders_of_the_same_symbol_consume_the_symbol_cap() -> None:
    pending = (PendingExposure(symbol=_SYMBOL, amount=_NAV * PAPER_RISK_LIMITS.symbol_exposure),)

    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=pending))

    (order,) = evaluation.orders
    assert order.quantity == 0
    assert order.reject_code == RiskRule.SYMBOL_EXPOSURE.value


def test_partial_pending_exposure_leaves_room_for_the_remainder() -> None:
    pending = (PendingExposure(symbol=_SYMBOL, amount=Decimal(500_000)),)

    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=pending))

    assert [order.quantity for order in evaluation.orders] == [2]
    assert all(order.reject_code is None for order in evaluation.orders)


def test_pending_exposure_also_counts_towards_total_exposure() -> None:
    pending = (PendingExposure(symbol=_SYMBOL, amount=_NAV * PAPER_RISK_LIMITS.total_exposure),)

    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=pending))

    (order,) = evaluation.orders
    assert order.quantity == 0
    assert order.reject_code is not None


def test_no_pending_exposure_keeps_the_previous_behaviour() -> None:
    evaluation = evaluate_plan(_request(symbol=_SYMBOL, pending=()))

    assert [order.quantity for order in evaluation.orders] == [2, 2]
