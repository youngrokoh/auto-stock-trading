"""거래 안전 정책 §3 한도의 현재 소진율. 한도값은 정책 상수이며 여기서 완화하지 않는다."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.risk.limits import RiskRule

if TYPE_CHECKING:
    from collections.abc import Mapping

    from auto_stock_trading.domain.risk.limits import RiskLimits

_RATIO_EXPONENT: Final = Decimal("0.000001")
_ONE: Final = Decimal(1)


class UsageBasis(StrEnum):
    """소진율의 기준. 화면과 감사 로그가 같은 문자열을 쓴다."""

    NAV_RATIO = "nav_ratio"
    SESSION_OPEN_NAV_RATIO = "session_open_nav_ratio"
    PEAK_NAV_RATIO = "peak_nav_ratio"
    COUNT = "count"


class UsageComparison(StrEnum):
    AT_MOST = "at_most"
    AT_LEAST = "at_least"


class UsageReason(StrEnum):
    """현재값이나 소진율을 만들 수 없는 사유. 값을 추정해 채우지 않는다."""

    MISSING_SNAPSHOT = "MISSING_SNAPSHOT"
    MISSING_SESSION_OPEN_NAV = "MISSING_SESSION_OPEN_NAV"
    MISSING_PEAK_NAV = "MISSING_PEAK_NAV"
    MISSING_SECTOR_DATA = "MISSING_SECTOR_DATA"
    ZERO_BASIS = "ZERO_BASIS"


class _Mode(StrEnum):
    RATIO = auto()
    DELTA_RATIO = auto()
    COUNT = auto()


@dataclass(frozen=True, slots=True)
class UsageState:
    """소진율 계산에 쓰는 현재 상태. 없는 값은 `None`으로 남긴다."""

    nav: Decimal | None
    settled_cash: Decimal | None
    position_value: Decimal | None
    max_position_value: Decimal | None
    # 업종별 평가금액. None이면 업종 사실이 없어 소진율을 만들지 않는다.
    sector_values: tuple[tuple[str, Decimal], ...] | None
    unclassified_value: Decimal | None
    session_open_nav: Decimal | None
    peak_nav: Decimal | None
    max_order_amount: Decimal
    daily_buy_amount: Decimal
    open_orders: int
    daily_order_attempts: int
    consecutive_rejects: int
    api_failures: int


@dataclass(frozen=True, slots=True)
class LimitUsage:
    rule: RiskRule
    basis: UsageBasis
    comparison: UsageComparison
    limit_value: Decimal
    current_value: Decimal | None
    usage_ratio: Decimal | None
    reason: UsageReason | None


@dataclass(frozen=True, slots=True)
class _Spec:
    rule: RiskRule
    basis: UsageBasis
    comparison: UsageComparison
    mode: _Mode
    limit_value: Decimal
    numerator: Decimal | None
    denominator: Decimal | None
    missing: UsageReason
    # 현재값 자체를 만들 수 없을 때의 사유. 업종은 사실이 없을 때가 그렇다.
    missing_numerator: UsageReason | None = None


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(_RATIO_EXPONENT, rounding=ROUND_HALF_UP)


def _unknown(spec: _Spec, reason: UsageReason) -> LimitUsage:
    return LimitUsage(
        rule=spec.rule,
        basis=spec.basis,
        comparison=spec.comparison,
        limit_value=spec.limit_value,
        current_value=None,
        usage_ratio=None,
        reason=reason,
    )


def _current(spec: _Spec, numerator: Decimal, denominator: Decimal) -> Decimal:
    if spec.mode is _Mode.COUNT:
        return numerator
    if spec.mode is _Mode.DELTA_RATIO:
        return _ratio(numerator - denominator, denominator)
    return _ratio(numerator, denominator)


def _clamped(ratio: Decimal) -> Decimal:
    """음수 소진율은 0으로 둔다. 부호 있는 0이 응답에 나가지 않도록 다시 양자화한다."""
    return (ratio if ratio > 0 else Decimal(0)).quantize(_RATIO_EXPONENT)


def _usage_ratio(spec: _Spec, current: Decimal) -> Decimal | None:
    """한도에 얼마나 접근했는지. 1.0이 한도 도달, 1.0 초과가 위반이다."""
    if spec.comparison is UsageComparison.AT_MOST or spec.limit_value < 0:
        return _clamped(_ratio(current, spec.limit_value))
    if current <= 0:
        return None
    return _ratio(spec.limit_value, current)


def _limit_usage(spec: _Spec) -> LimitUsage:
    numerator = spec.numerator
    denominator = spec.denominator
    if numerator is None:
        return _unknown(spec, spec.missing_numerator or UsageReason.MISSING_SNAPSHOT)
    if denominator is None:
        return _unknown(spec, spec.missing)
    if denominator == 0:
        return _unknown(spec, UsageReason.ZERO_BASIS)
    current = _current(spec, numerator, denominator)
    ratio = _usage_ratio(spec, current)
    return LimitUsage(
        rule=spec.rule,
        basis=spec.basis,
        comparison=spec.comparison,
        limit_value=spec.limit_value,
        current_value=current,
        usage_ratio=ratio,
        reason=None if ratio is not None else UsageReason.ZERO_BASIS,
    )


def _nav_spec(
    rule: RiskRule,
    limit_value: Decimal,
    numerator: Decimal | None,
    nav: Decimal | None,
) -> _Spec:
    return _Spec(
        rule=rule,
        basis=UsageBasis.NAV_RATIO,
        comparison=UsageComparison.AT_MOST,
        mode=_Mode.RATIO,
        limit_value=limit_value,
        numerator=numerator,
        denominator=nav,
        missing=UsageReason.MISSING_SNAPSHOT,
    )


def classify_positions(
    holdings: tuple[tuple[str, Decimal], ...],
    sectors: Mapping[str, str],
) -> tuple[tuple[tuple[str, Decimal], ...], Decimal]:
    """보유 평가금액을 업종별 합계와 미분류 합계로 나눈다(정책 §3).

    업종 사실이 없는 종목은 미분류로 남는다. 분류를 추정해 채우지 않는다.
    """
    classified: dict[str, Decimal] = {}
    unclassified = Decimal(0)
    for symbol, value in holdings:
        sector = sectors.get(symbol)
        if sector is None:
            unclassified += value
            continue
        classified[sector] = classified.get(sector, Decimal(0)) + value
    return tuple(sorted(classified.items())), unclassified


def _tightest_sector(values: tuple[tuple[str, Decimal], ...] | None) -> Decimal | None:
    """가장 많이 찬 업종이 한도를 결정한다. 업종 사실이 없으면 값을 만들지 않는다."""
    if values is None:
        return None
    return max((value for _, value in values), default=Decimal(0))


def _count_spec(rule: RiskRule, limit_value: int, current: int) -> _Spec:
    return _Spec(
        rule=rule,
        basis=UsageBasis.COUNT,
        comparison=UsageComparison.AT_MOST,
        mode=_Mode.COUNT,
        limit_value=Decimal(limit_value),
        numerator=Decimal(current),
        denominator=_ONE,
        missing=UsageReason.MISSING_SNAPSHOT,
    )


def _specs(state: UsageState, limits: RiskLimits) -> tuple[_Spec, ...]:
    nav = state.nav
    return (
        _nav_spec(RiskRule.TOTAL_EXPOSURE, limits.total_exposure, state.position_value, nav),
        _Spec(
            rule=RiskRule.MIN_CASH,
            basis=UsageBasis.NAV_RATIO,
            comparison=UsageComparison.AT_LEAST,
            mode=_Mode.RATIO,
            limit_value=limits.min_cash,
            numerator=state.settled_cash,
            denominator=nav,
            missing=UsageReason.MISSING_SNAPSHOT,
        ),
        _nav_spec(
            RiskRule.SYMBOL_EXPOSURE,
            limits.symbol_exposure,
            state.max_position_value,
            nav,
        ),
        _Spec(
            rule=RiskRule.SECTOR_EXPOSURE,
            basis=UsageBasis.NAV_RATIO,
            comparison=UsageComparison.AT_MOST,
            mode=_Mode.RATIO,
            limit_value=limits.sector_exposure,
            numerator=_tightest_sector(state.sector_values),
            denominator=nav,
            missing=UsageReason.MISSING_SECTOR_DATA,
            missing_numerator=UsageReason.MISSING_SECTOR_DATA,
        ),
        _nav_spec(
            RiskRule.UNCLASSIFIED_EXPOSURE,
            limits.unclassified_exposure,
            state.unclassified_value,
            nav,
        ),
        _nav_spec(RiskRule.ORDER_AMOUNT, limits.order_amount, state.max_order_amount, nav),
        _Spec(
            rule=RiskRule.DAILY_BUY_AMOUNT,
            basis=UsageBasis.SESSION_OPEN_NAV_RATIO,
            comparison=UsageComparison.AT_MOST,
            mode=_Mode.RATIO,
            limit_value=limits.daily_buy_amount,
            numerator=state.daily_buy_amount,
            denominator=state.session_open_nav,
            missing=UsageReason.MISSING_SESSION_OPEN_NAV,
        ),
        _count_spec(RiskRule.OPEN_ORDERS, limits.open_orders, state.open_orders),
        _count_spec(
            RiskRule.DAILY_ORDER_ATTEMPTS,
            limits.daily_order_attempts,
            state.daily_order_attempts,
        ),
        _Spec(
            rule=RiskRule.DAILY_LOSS,
            basis=UsageBasis.SESSION_OPEN_NAV_RATIO,
            comparison=UsageComparison.AT_LEAST,
            mode=_Mode.DELTA_RATIO,
            limit_value=limits.daily_loss,
            numerator=nav,
            denominator=state.session_open_nav,
            missing=UsageReason.MISSING_SESSION_OPEN_NAV,
        ),
        _Spec(
            rule=RiskRule.DRAWDOWN,
            basis=UsageBasis.PEAK_NAV_RATIO,
            comparison=UsageComparison.AT_LEAST,
            mode=_Mode.DELTA_RATIO,
            limit_value=limits.drawdown,
            numerator=nav,
            denominator=state.peak_nav,
            missing=UsageReason.MISSING_PEAK_NAV,
        ),
        _count_spec(
            RiskRule.CONSECUTIVE_REJECTS,
            limits.consecutive_rejects,
            state.consecutive_rejects,
        ),
        _count_spec(RiskRule.API_FAILURES, limits.api_failures, state.api_failures),
    )


def limit_usage(state: UsageState, limits: RiskLimits) -> tuple[LimitUsage, ...]:
    """정책 §3의 한도 13종을 정책 표 순서대로 계산한다."""
    return tuple(_limit_usage(spec) for spec in _specs(state, limits))
