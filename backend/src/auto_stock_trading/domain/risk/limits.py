from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from enum import StrEnum
from typing import Final


class RiskRule(StrEnum):
    """거래 안전 정책 §3의 한도와 §4의 수량·가격 조건."""

    TOTAL_EXPOSURE = "RISK_TOTAL_EXPOSURE"
    MIN_CASH = "RISK_MIN_CASH"
    SYMBOL_EXPOSURE = "RISK_SYMBOL_EXPOSURE"
    SECTOR_EXPOSURE = "RISK_SECTOR_EXPOSURE"
    UNCLASSIFIED_EXPOSURE = "RISK_UNCLASSIFIED_EXPOSURE"
    ORDER_AMOUNT = "RISK_ORDER_AMOUNT"
    DAILY_BUY_AMOUNT = "RISK_DAILY_BUY_AMOUNT"
    OPEN_ORDERS = "RISK_OPEN_ORDERS"
    DAILY_ORDER_ATTEMPTS = "RISK_DAILY_ORDER_ATTEMPTS"
    DAILY_LOSS = "RISK_DAILY_LOSS"
    DRAWDOWN = "RISK_DRAWDOWN"
    CONSECUTIVE_REJECTS = "RISK_CONSECUTIVE_REJECTS"
    API_FAILURES = "RISK_API_FAILURES"
    ORDERABLE_CASH = "RISK_ORDERABLE_CASH"
    ORDERABLE_QUANTITY = "RISK_ORDERABLE_QUANTITY"
    ORDER_PRICE_BAND = "RISK_ORDER_PRICE_BAND"


class BlockCode(StrEnum):
    """거래 안전 정책 §7.2의 차단 사유 코드."""

    API_CONSECUTIVE_FAILURE = "API_CONSECUTIVE_FAILURE"
    ACCOUNT_NOT_RECONCILED = "ACCOUNT_NOT_RECONCILED"
    DATA_STALE = "DATA_STALE"
    SYMBOL_SUSPENDED = "SYMBOL_SUSPENDED"
    MARKET_CLOSED = "MARKET_CLOSED"
    SOURCE_TIMEOUT = "SOURCE_TIMEOUT"
    AUTOMATION_NOT_RUNNING = "AUTOMATION_NOT_RUNNING"


# 이 값은 거래 안전 정책 §3·§4의 승인된 한도다. 코드에서 완화할 수 없다.
@dataclass(frozen=True, slots=True)
class RiskLimits:
    total_exposure: Decimal
    min_cash: Decimal
    symbol_exposure: Decimal
    sector_exposure: Decimal
    unclassified_exposure: Decimal
    order_amount: Decimal
    daily_buy_amount: Decimal
    open_orders: int
    daily_order_attempts: int
    daily_loss: Decimal
    drawdown: Decimal
    consecutive_rejects: int
    api_failures: int
    api_failure_window_seconds: int
    order_window_start: time
    order_window_end: time
    quote_max_age_seconds: int
    price_band: Decimal


PAPER_RISK_LIMITS: Final = RiskLimits(
    total_exposure=Decimal("0.80"),
    min_cash=Decimal("0.20"),
    symbol_exposure=Decimal("0.10"),
    sector_exposure=Decimal("0.30"),
    unclassified_exposure=Decimal("0.10"),
    order_amount=Decimal("0.05"),
    daily_buy_amount=Decimal("0.20"),
    open_orders=5,
    daily_order_attempts=20,
    daily_loss=Decimal("-0.02"),
    drawdown=Decimal("-0.05"),
    consecutive_rejects=3,
    api_failures=3,
    api_failure_window_seconds=300,
    order_window_start=time(9, 5),
    order_window_end=time(15, 15),
    quote_max_age_seconds=10,
    price_band=Decimal("0.01"),
)
