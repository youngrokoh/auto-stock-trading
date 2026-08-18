from dataclasses import replace
from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.risk.limits import PAPER_RISK_LIMITS, RiskRule
from auto_stock_trading.domain.risk.utilization import (
    LimitUsage,
    UsageBasis,
    UsageComparison,
    UsageReason,
    UsageState,
    limit_usage,
)

_NAV: Final = Decimal(100_000_000)
_STATE: Final = UsageState(
    nav=_NAV,
    cash_balance=Decimal(80_000_000),
    position_value=Decimal(20_000_000),
    max_position_value=Decimal(8_000_000),
    session_open_nav=_NAV,
    peak_nav=_NAV,
    max_order_amount=Decimal(4_000_000),
    daily_buy_amount=Decimal(10_000_000),
    open_orders=2,
    daily_order_attempts=6,
    consecutive_rejects=1,
    api_failures=0,
)


def _usage(state: UsageState, rule: RiskRule) -> LimitUsage:
    found = [item for item in limit_usage(state, PAPER_RISK_LIMITS) if item.rule == rule]
    assert len(found) == 1
    return found[0]


def test_every_policy_limit_is_reported_once_in_policy_order() -> None:
    items = limit_usage(_STATE, PAPER_RISK_LIMITS)

    assert [item.rule for item in items] == [
        RiskRule.TOTAL_EXPOSURE,
        RiskRule.MIN_CASH,
        RiskRule.SYMBOL_EXPOSURE,
        RiskRule.SECTOR_EXPOSURE,
        RiskRule.UNCLASSIFIED_EXPOSURE,
        RiskRule.ORDER_AMOUNT,
        RiskRule.DAILY_BUY_AMOUNT,
        RiskRule.OPEN_ORDERS,
        RiskRule.DAILY_ORDER_ATTEMPTS,
        RiskRule.DAILY_LOSS,
        RiskRule.DRAWDOWN,
        RiskRule.CONSECUTIVE_REJECTS,
        RiskRule.API_FAILURES,
    ]


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (
            RiskRule.TOTAL_EXPOSURE,
            LimitUsage(
                rule=RiskRule.TOTAL_EXPOSURE,
                basis=UsageBasis.NAV_RATIO,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal("0.80"),
                current_value=Decimal("0.200000"),
                usage_ratio=Decimal("0.250000"),
                reason=None,
            ),
        ),
        (
            RiskRule.MIN_CASH,
            LimitUsage(
                rule=RiskRule.MIN_CASH,
                basis=UsageBasis.NAV_RATIO,
                comparison=UsageComparison.AT_LEAST,
                limit_value=Decimal("0.20"),
                current_value=Decimal("0.800000"),
                usage_ratio=Decimal("0.250000"),
                reason=None,
            ),
        ),
        (
            RiskRule.SYMBOL_EXPOSURE,
            LimitUsage(
                rule=RiskRule.SYMBOL_EXPOSURE,
                basis=UsageBasis.NAV_RATIO,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal("0.10"),
                current_value=Decimal("0.080000"),
                usage_ratio=Decimal("0.800000"),
                reason=None,
            ),
        ),
        (
            RiskRule.UNCLASSIFIED_EXPOSURE,
            LimitUsage(
                rule=RiskRule.UNCLASSIFIED_EXPOSURE,
                basis=UsageBasis.NAV_RATIO,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal("0.10"),
                current_value=Decimal("0.200000"),
                usage_ratio=Decimal("2.000000"),
                reason=None,
            ),
        ),
        (
            RiskRule.ORDER_AMOUNT,
            LimitUsage(
                rule=RiskRule.ORDER_AMOUNT,
                basis=UsageBasis.NAV_RATIO,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal("0.05"),
                current_value=Decimal("0.040000"),
                usage_ratio=Decimal("0.800000"),
                reason=None,
            ),
        ),
        (
            RiskRule.DAILY_BUY_AMOUNT,
            LimitUsage(
                rule=RiskRule.DAILY_BUY_AMOUNT,
                basis=UsageBasis.SESSION_OPEN_NAV_RATIO,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal("0.20"),
                current_value=Decimal("0.100000"),
                usage_ratio=Decimal("0.500000"),
                reason=None,
            ),
        ),
        (
            RiskRule.OPEN_ORDERS,
            LimitUsage(
                rule=RiskRule.OPEN_ORDERS,
                basis=UsageBasis.COUNT,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal(5),
                current_value=Decimal(2),
                usage_ratio=Decimal("0.400000"),
                reason=None,
            ),
        ),
        (
            RiskRule.DAILY_ORDER_ATTEMPTS,
            LimitUsage(
                rule=RiskRule.DAILY_ORDER_ATTEMPTS,
                basis=UsageBasis.COUNT,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal(20),
                current_value=Decimal(6),
                usage_ratio=Decimal("0.300000"),
                reason=None,
            ),
        ),
        (
            RiskRule.CONSECUTIVE_REJECTS,
            LimitUsage(
                rule=RiskRule.CONSECUTIVE_REJECTS,
                basis=UsageBasis.COUNT,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal(3),
                current_value=Decimal(1),
                usage_ratio=Decimal("0.333333"),
                reason=None,
            ),
        ),
        (
            RiskRule.API_FAILURES,
            LimitUsage(
                rule=RiskRule.API_FAILURES,
                basis=UsageBasis.COUNT,
                comparison=UsageComparison.AT_MOST,
                limit_value=Decimal(3),
                current_value=Decimal(0),
                usage_ratio=Decimal("0.000000"),
                reason=None,
            ),
        ),
    ],
)
def test_computable_limits_report_current_value_and_usage_ratio(
    rule: RiskRule,
    expected: LimitUsage,
) -> None:
    assert _usage(_STATE, rule) == expected


def test_sector_exposure_has_no_current_value_without_sector_data() -> None:
    usage = _usage(_STATE, RiskRule.SECTOR_EXPOSURE)

    assert usage.current_value is None
    assert usage.usage_ratio is None
    assert usage.reason is UsageReason.MISSING_SECTOR_DATA
    assert usage.limit_value == Decimal("0.30")


def test_daily_loss_and_drawdown_use_signed_ratios() -> None:
    state = replace(
        _STATE,
        nav=Decimal(98_000_000),
        session_open_nav=Decimal(100_000_000),
        peak_nav=Decimal(100_000_000),
    )

    daily_loss = _usage(state, RiskRule.DAILY_LOSS)
    drawdown = _usage(state, RiskRule.DRAWDOWN)

    assert daily_loss.basis is UsageBasis.SESSION_OPEN_NAV_RATIO
    assert daily_loss.comparison is UsageComparison.AT_LEAST
    assert daily_loss.limit_value == Decimal("-0.02")
    assert daily_loss.current_value == Decimal("-0.020000")
    assert daily_loss.usage_ratio == Decimal("1.000000")
    assert drawdown.basis is UsageBasis.PEAK_NAV_RATIO
    assert drawdown.current_value == Decimal("-0.020000")
    assert drawdown.usage_ratio == Decimal("0.400000")


def test_profit_leaves_loss_limits_unused() -> None:
    state = replace(_STATE, nav=Decimal(101_000_000), peak_nav=Decimal(101_000_000))

    assert _usage(state, RiskRule.DAILY_LOSS).current_value == Decimal("0.010000")
    assert _usage(state, RiskRule.DAILY_LOSS).usage_ratio == Decimal(0)
    assert _usage(state, RiskRule.DRAWDOWN).current_value == Decimal("0.000000")
    assert _usage(state, RiskRule.DRAWDOWN).usage_ratio == Decimal(0)


def test_cash_below_minimum_reports_usage_above_one() -> None:
    state = replace(_STATE, cash_balance=Decimal(10_000_000))

    usage = _usage(state, RiskRule.MIN_CASH)

    assert usage.current_value == Decimal("0.100000")
    assert usage.usage_ratio == Decimal("2.000000")


def test_zero_cash_leaves_minimum_cash_ratio_unknown() -> None:
    state = replace(_STATE, cash_balance=Decimal(0))

    usage = _usage(state, RiskRule.MIN_CASH)

    assert usage.current_value == Decimal("0.000000")
    assert usage.usage_ratio is None
    assert usage.reason is UsageReason.ZERO_BASIS


def test_missing_snapshot_leaves_every_amount_limit_unknown() -> None:
    state = UsageState(
        nav=None,
        cash_balance=None,
        position_value=None,
        max_position_value=None,
        session_open_nav=None,
        peak_nav=None,
        max_order_amount=Decimal(0),
        daily_buy_amount=Decimal(0),
        open_orders=0,
        daily_order_attempts=0,
        consecutive_rejects=0,
        api_failures=0,
    )

    items = limit_usage(state, PAPER_RISK_LIMITS)
    unknown = {item.rule: item.reason for item in items if item.current_value is None}

    assert unknown == {
        RiskRule.TOTAL_EXPOSURE: UsageReason.MISSING_SNAPSHOT,
        RiskRule.MIN_CASH: UsageReason.MISSING_SNAPSHOT,
        RiskRule.SYMBOL_EXPOSURE: UsageReason.MISSING_SNAPSHOT,
        RiskRule.SECTOR_EXPOSURE: UsageReason.MISSING_SECTOR_DATA,
        RiskRule.UNCLASSIFIED_EXPOSURE: UsageReason.MISSING_SNAPSHOT,
        RiskRule.ORDER_AMOUNT: UsageReason.MISSING_SNAPSHOT,
        RiskRule.DAILY_BUY_AMOUNT: UsageReason.MISSING_SESSION_OPEN_NAV,
        RiskRule.DAILY_LOSS: UsageReason.MISSING_SNAPSHOT,
        RiskRule.DRAWDOWN: UsageReason.MISSING_SNAPSHOT,
    }
    assert [item.current_value for item in items if item.basis is UsageBasis.COUNT] == [
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    ]


def test_missing_session_open_nav_only_affects_session_limits() -> None:
    state = replace(_STATE, session_open_nav=None)

    assert _usage(state, RiskRule.DAILY_BUY_AMOUNT).reason is UsageReason.MISSING_SESSION_OPEN_NAV
    assert _usage(state, RiskRule.DAILY_LOSS).reason is UsageReason.MISSING_SESSION_OPEN_NAV
    assert _usage(state, RiskRule.TOTAL_EXPOSURE).reason is None


def test_missing_peak_nav_only_affects_drawdown() -> None:
    state = replace(_STATE, peak_nav=None)

    assert _usage(state, RiskRule.DRAWDOWN).reason is UsageReason.MISSING_PEAK_NAV
    assert _usage(state, RiskRule.DAILY_LOSS).reason is None


def test_zero_nav_leaves_exposure_ratios_unknown() -> None:
    state = replace(_STATE, nav=Decimal(0))

    usage = _usage(state, RiskRule.TOTAL_EXPOSURE)

    assert usage.current_value is None
    assert usage.reason is UsageReason.ZERO_BASIS
