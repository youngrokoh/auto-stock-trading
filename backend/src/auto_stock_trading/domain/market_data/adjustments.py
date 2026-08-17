import hashlib
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
)
from auto_stock_trading.domain.market_data.models import BarFinality

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from uuid import UUID

    from auto_stock_trading.domain.market_data.corporate_actions import VersionedCorporateAction

ADJUSTMENT_ALGORITHM_VERSION: Final = "krx-t2-adjust-v1"
_PRICE_QUANTUM: Final = Decimal("1E-8")
_FACTOR_QUANTUM: Final = Decimal("1E-16")
_CONTEXT_PRECISION: Final = 34
_SHARE_TYPES: Final = frozenset(
    {
        CorporateActionType.STOCK_SPLIT,
        CorporateActionType.REVERSE_SPLIT,
        CorporateActionType.STOCK_DIVIDEND,
    }
)
_CASH_TYPES: Final = frozenset(
    {CorporateActionType.CASH_DIVIDEND, CorporateActionType.ETF_DISTRIBUTION}
)
_UNSUPPORTED_TYPES: Final = frozenset(
    {
        CorporateActionType.RIGHTS_ISSUE,
        CorporateActionType.CAPITAL_REDUCTION,
        CorporateActionType.MERGER,
        CorporateActionType.SPIN_OFF,
    }
)


class AdjustmentMethod(StrEnum):
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN = "total_return"


class AdjustmentFailure(StrEnum):
    CALENDAR_COVERAGE = "calendar_coverage_missing"
    UNCONFIRMED_BAR = "unconfirmed_bar_in_range"
    MISSING_BAR = "missing_bar_unexplained"
    BAR_OUTSIDE_CALENDAR = "bar_outside_trading_calendar"
    UNSUPPORTED_ACTION = "unsupported_action_in_range"
    CONFLICTING_ACTION = "conflicting_action_in_range"
    MISSING_CONDITIONS = "missing_action_conditions"
    INVALID_SHARE_MULTIPLIER = "invalid_share_multiplier"
    MISSING_PRIOR_CLOSE = "missing_prior_close"
    INVALID_CASH_FACTOR = "invalid_cash_factor"
    MIXED_SAME_DAY_BASIS = "same_day_cash_share_basis_unknown"
    INVALID_RESULT = "invalid_adjusted_values"


@dataclass(frozen=True, slots=True)
class AdjustmentError(Exception):
    failure: AdjustmentFailure

    @override
    def __str__(self) -> str:
        return self.failure.value


@dataclass(frozen=True, slots=True)
class InputBar:
    bar_id: UUID
    version: int
    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    finality: BarFinality


@dataclass(frozen=True, slots=True)
class AppliedAction:
    action: VersionedCorporateAction
    event_date: date
    price_factor: Decimal
    volume_factor: Decimal


@dataclass(frozen=True, slots=True)
class AdjustedBarValues:
    source: InputBar
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal
    price_factor: Decimal
    volume_factor: Decimal


@dataclass(frozen=True, slots=True)
class AdjustmentPlan:
    applied_actions: tuple[AppliedAction, ...]
    adjusted_bars: tuple[AdjustedBarValues, ...]
    input_bar_version_hash: str
    action_version_hash: str


@dataclass(frozen=True, slots=True)
class AdjustmentInputs:
    method: AdjustmentMethod
    range_start: date
    price_cutoff_date: date
    bars: tuple[InputBar, ...]
    actions: tuple[VersionedCorporateAction, ...]
    open_dates: tuple[date, ...]
    listed_on: date | None
    delisted_on: date | None


def input_bar_version_hash(bars: Sequence[InputBar]) -> str:
    lines = "\n".join(
        f"{bar.trading_date.isoformat()}:{bar.bar_id}:{bar.version}"
        for bar in sorted(bars, key=lambda bar: bar.trading_date)
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def action_version_hash(applied_actions: Sequence[AppliedAction]) -> str:
    lines = "\n".join(
        f"{item.event_date.isoformat()}:{item.action.action_key}:{item.action.version}"
        for item in sorted(
            applied_actions,
            key=lambda item: (item.event_date, str(item.action.action_key)),
        )
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def build_adjustment_plan(inputs: AdjustmentInputs) -> AdjustmentPlan:
    ordered_bars = tuple(sorted(inputs.bars, key=lambda bar: bar.trading_date))
    expected_dates = tuple(
        day
        for day in sorted(inputs.open_dates)
        if inputs.range_start <= day <= inputs.price_cutoff_date
    )
    _require_complete_confirmed_bars(
        ordered_bars,
        expected_dates,
        listed_on=inputs.listed_on,
        delisted_on=inputs.delisted_on,
    )
    relevant = _judged_actions(inputs.actions, inputs.range_start, inputs.price_cutoff_date)
    with localcontext() as context:
        context.prec = _CONTEXT_PRECISION
        applied = _applied_actions(inputs.method, relevant, ordered_bars)
        adjusted = _adjusted_bars(ordered_bars, applied)
    return AdjustmentPlan(
        applied_actions=applied,
        adjusted_bars=adjusted,
        input_bar_version_hash=input_bar_version_hash(ordered_bars),
        action_version_hash=action_version_hash(applied),
    )


def _require_complete_confirmed_bars(
    bars: tuple[InputBar, ...],
    expected_dates: tuple[date, ...],
    *,
    listed_on: date | None,
    delisted_on: date | None,
) -> None:
    bar_dates = {bar.trading_date for bar in bars}
    if len(bar_dates) != len(bars) or not bar_dates.issubset(set(expected_dates)):
        raise AdjustmentError(AdjustmentFailure.BAR_OUTSIDE_CALENDAR)
    for bar in bars:
        if bar.finality is not BarFinality.CONFIRMED:
            raise AdjustmentError(AdjustmentFailure.UNCONFIRMED_BAR)
    for day in expected_dates:
        if day in bar_dates:
            continue
        if listed_on is not None and day < listed_on:
            continue
        if delisted_on is not None and day > delisted_on:
            continue
        raise AdjustmentError(AdjustmentFailure.MISSING_BAR)


def _judged_actions(
    actions: Sequence[VersionedCorporateAction],
    range_start: date,
    price_cutoff_date: date,
) -> tuple[VersionedCorporateAction, ...]:
    relevant: list[VersionedCorporateAction] = []
    for item in actions:
        action = item.action
        if action.lifecycle is CorporateActionLifecycle.CANCELLED:
            continue
        best_known = action.ex_date or action.effective_date or action.record_date
        in_range = best_known is not None and range_start < best_known <= price_cutoff_date
        if not in_range:
            continue
        if action.quality is CorporateActionQuality.CONFLICT:
            raise AdjustmentError(AdjustmentFailure.CONFLICTING_ACTION)
        if action.action_type in _UNSUPPORTED_TYPES:
            raise AdjustmentError(AdjustmentFailure.UNSUPPORTED_ACTION)
        if action.action_type in _SHARE_TYPES:
            _require_share_conditions(item)
            relevant.append(item)
        elif action.action_type in _CASH_TYPES:
            _require_cash_conditions(item)
            relevant.append(item)
    return tuple(relevant)


def _require_share_conditions(item: VersionedCorporateAction) -> None:
    action = item.action
    if (action.ex_date or action.effective_date) is None or action.share_multiplier is None:
        raise AdjustmentError(AdjustmentFailure.MISSING_CONDITIONS)
    multiplier = action.share_multiplier
    if action.action_type is CorporateActionType.REVERSE_SPLIT:
        if not Decimal(0) < multiplier < Decimal(1):
            raise AdjustmentError(AdjustmentFailure.INVALID_SHARE_MULTIPLIER)
    elif multiplier <= Decimal(1):
        raise AdjustmentError(AdjustmentFailure.INVALID_SHARE_MULTIPLIER)


def _require_cash_conditions(item: VersionedCorporateAction) -> None:
    action = item.action
    if action.ex_date is None or action.cash_amount is None or action.currency is None:
        raise AdjustmentError(AdjustmentFailure.MISSING_CONDITIONS)
    if action.currency != "KRW" or action.cash_amount <= 0:
        raise AdjustmentError(AdjustmentFailure.INVALID_CASH_FACTOR)


def _event_date(item: VersionedCorporateAction) -> date:
    action = item.action
    event = (
        action.ex_date
        if action.action_type in _CASH_TYPES
        else (action.ex_date or action.effective_date)
    )
    if event is None:
        raise AdjustmentError(AdjustmentFailure.MISSING_CONDITIONS)
    return event


def _applied_actions(
    method: AdjustmentMethod,
    relevant: tuple[VersionedCorporateAction, ...],
    bars: tuple[InputBar, ...],
) -> tuple[AppliedAction, ...]:
    share_dates = {
        _event_date(item) for item in relevant if item.action.action_type in _SHARE_TYPES
    }
    applied: list[AppliedAction] = []
    ordered = sorted(
        relevant,
        key=lambda item: (
            _event_date(item),
            item.action.action_type in _CASH_TYPES,
            str(item.action_key),
        ),
    )
    for item in ordered:
        event = _event_date(item)
        if item.action.action_type in _SHARE_TYPES:
            multiplier = item.action.share_multiplier
            assert multiplier is not None  # guarded by _require_share_conditions
            applied.append(
                AppliedAction(
                    action=item,
                    event_date=event,
                    price_factor=_quantize_factor(Decimal(1) / multiplier),
                    volume_factor=_quantize_factor(multiplier),
                )
            )
            continue
        if method is not AdjustmentMethod.TOTAL_RETURN:
            continue
        if event in share_dates:
            raise AdjustmentError(AdjustmentFailure.MIXED_SAME_DAY_BASIS)
        applied.append(
            AppliedAction(
                action=item,
                event_date=event,
                price_factor=_cash_price_factor(item, event, bars),
                volume_factor=_quantize_factor(Decimal(1)),
            )
        )
    return tuple(applied)


def _cash_price_factor(
    item: VersionedCorporateAction,
    event: date,
    bars: tuple[InputBar, ...],
) -> Decimal:
    prior = [bar for bar in bars if bar.trading_date < event]
    if not prior:
        raise AdjustmentError(AdjustmentFailure.MISSING_PRIOR_CLOSE)
    prior_close = prior[-1].close_price
    cash_amount = item.action.cash_amount
    assert cash_amount is not None  # guarded by _require_cash_conditions
    if prior_close <= 0 or prior_close - cash_amount <= 0:
        raise AdjustmentError(AdjustmentFailure.INVALID_CASH_FACTOR)
    return _quantize_factor((prior_close - cash_amount) / prior_close)


def _adjusted_bars(
    bars: tuple[InputBar, ...],
    applied: tuple[AppliedAction, ...],
) -> tuple[AdjustedBarValues, ...]:
    adjusted: list[AdjustedBarValues] = []
    for bar in bars:
        price_factor = Decimal(1)
        volume_factor = Decimal(1)
        for item in applied:
            if item.event_date > bar.trading_date:
                price_factor *= item.price_factor
                volume_factor *= item.volume_factor
        values = AdjustedBarValues(
            source=bar,
            open_price=_quantize_price(bar.open_price * price_factor),
            high_price=_quantize_price(bar.high_price * price_factor),
            low_price=_quantize_price(bar.low_price * price_factor),
            close_price=_quantize_price(bar.close_price * price_factor),
            volume=int(
                (Decimal(bar.volume) * volume_factor).to_integral_value(rounding=ROUND_HALF_UP)
            ),
            trading_value=bar.trading_value,
            price_factor=_quantize_factor(price_factor),
            volume_factor=_quantize_factor(volume_factor),
        )
        _require_valid_values(values)
        adjusted.append(values)
    return tuple(adjusted)


def _require_valid_values(values: AdjustedBarValues) -> None:
    valid = (
        values.low_price <= values.open_price <= values.high_price
        and values.low_price <= values.close_price <= values.high_price
        and values.volume >= 0
        and values.price_factor > 0
        and values.volume_factor > 0
    )
    if not valid:
        raise AdjustmentError(AdjustmentFailure.INVALID_RESULT)


def _quantize_price(value: Decimal) -> Decimal:
    return value.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def _quantize_factor(value: Decimal) -> Decimal:
    return value.quantize(_FACTOR_QUANTUM, rounding=ROUND_HALF_UP)
