from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from auto_stock_trading.domain.market_data.adjustments import (
    AdjustmentError,
    AdjustmentFailure,
    AdjustmentInputs,
    AdjustmentMethod,
    AdjustmentPlan,
    AppliedAction,
    InputBar,
    action_version_hash,
    build_adjustment_plan,
    input_bar_version_hash,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    TimePrecision,
    VersionedCorporateAction,
)
from auto_stock_trading.domain.market_data.models import BarFinality

_OPEN_DATES = (
    date(2026, 8, 3),
    date(2026, 8, 4),
    date(2026, 8, 5),
    date(2026, 8, 6),
    date(2026, 8, 7),
)
_RECEIVED_AT = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
_DEFAULT_CLOSE = Decimal(1000)
_DEFAULT_EX_DATE = date(2026, 8, 5)
_SPLIT_ACTION = CorporateAction(
    action_type=CorporateActionType.STOCK_SPLIT,
    lifecycle=CorporateActionLifecycle.CONFIRMED,
    quality=CorporateActionQuality.VERIFIED,
    announced_at=None,
    announcement_date=date(2026, 7, 1),
    time_precision=TimePrecision.DATE,
    ex_date=date(2026, 8, 5),
    effective_date=None,
    record_date=None,
    payment_date=None,
    share_multiplier=Decimal(5),
    cash_amount=None,
    currency=None,
    subscription_price=None,
    related_instrument_id=None,
    source="TEST",
    source_event_id="test-action",
    source_reference="https://example.test/action",
    available_at=_RECEIVED_AT,
    received_at=_RECEIVED_AT,
)


def _bar(
    trading_date: date,
    *,
    close: Decimal = _DEFAULT_CLOSE,
    volume: int = 100,
    identity: tuple[UUID, int] | None = None,
    finality: BarFinality = BarFinality.CONFIRMED,
) -> InputBar:
    bar_id, version = identity if identity is not None else (uuid4(), 1)
    return InputBar(
        bar_id=bar_id,
        version=version,
        trading_date=trading_date,
        open_price=close - Decimal(10),
        high_price=close + Decimal(20),
        low_price=close - Decimal(20),
        close_price=close,
        volume=volume,
        trading_value=Decimal(1_000_000),
        finality=finality,
    )


def _bars() -> tuple[InputBar, ...]:
    return tuple(_bar(day) for day in _OPEN_DATES)


def _versioned(
    action: CorporateAction,
    *,
    action_key: UUID | None = None,
    version: int = 1,
) -> VersionedCorporateAction:
    return VersionedCorporateAction(
        action=action,
        corporate_action_id=uuid4(),
        action_key=action_key if action_key is not None else uuid4(),
        version=version,
        valid_from=_RECEIVED_AT,
        superseded_at=None,
    )


def _dividend(
    cash_amount: Decimal,
    *,
    ex_date: date | None = _DEFAULT_EX_DATE,
    record_date: date | None = None,
    quality: CorporateActionQuality = CorporateActionQuality.VERIFIED,
) -> CorporateAction:
    return replace(
        _SPLIT_ACTION,
        action_type=CorporateActionType.CASH_DIVIDEND,
        ex_date=ex_date,
        record_date=record_date,
        share_multiplier=None,
        cash_amount=cash_amount,
        currency="KRW",
        quality=quality,
    )


def _plan(
    method: AdjustmentMethod,
    bars: tuple[InputBar, ...],
    actions: tuple[VersionedCorporateAction, ...],
    *,
    listed_on: date | None = None,
) -> AdjustmentPlan:
    return build_adjustment_plan(
        AdjustmentInputs(
            method=method,
            range_start=_OPEN_DATES[0],
            price_cutoff_date=_OPEN_DATES[-1],
            bars=bars,
            actions=actions,
            open_dates=_OPEN_DATES,
            listed_on=listed_on,
            delisted_on=None,
        )
    )


def test_input_hashes_match_pinned_serialization_vectors() -> None:
    bars = (
        _bar(
            date(2026, 8, 3),
            identity=(UUID("11111111-1111-1111-1111-111111111111"), 1),
        ),
        _bar(
            date(2026, 8, 4),
            identity=(UUID("22222222-2222-2222-2222-222222222222"), 2),
        ),
    )
    applied = (
        AppliedAction(
            action=_versioned(
                replace(_SPLIT_ACTION, ex_date=date(2026, 8, 4)),
                action_key=UUID("33333333-3333-3333-3333-333333333333"),
            ),
            event_date=date(2026, 8, 4),
            price_factor=Decimal("0.2"),
            volume_factor=Decimal(5),
        ),
    )

    assert (
        input_bar_version_hash(bars)
        == "89330f32205ac547836447a39f37b8a09ed771e1da50738b05a10349b91b222f"
    )
    assert (
        action_version_hash(applied)
        == "718a4680cafff28ba1683d329ec1771fed81d1be1e9c3866f3e2a468aefedc8b"
    )
    assert (
        action_version_hash(())
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_five_for_one_split_adjusts_prior_prices_and_volume() -> None:
    split = _versioned(_SPLIT_ACTION)

    plan = _plan(AdjustmentMethod.SPLIT_ADJUSTED, _bars(), (split,))

    by_date = {item.source.trading_date: item for item in plan.adjusted_bars}
    assert len(plan.applied_actions) == 1
    assert plan.applied_actions[0].price_factor == Decimal("0.2000000000000000")
    assert plan.applied_actions[0].volume_factor == Decimal("5.0000000000000000")
    assert by_date[date(2026, 8, 4)].close_price == Decimal("200.00000000")
    assert by_date[date(2026, 8, 4)].volume == 500
    assert by_date[date(2026, 8, 4)].trading_value == Decimal(1_000_000)
    assert by_date[date(2026, 8, 5)].close_price == Decimal("1000.00000000")
    assert by_date[date(2026, 8, 5)].volume == 100


def test_reverse_split_rounds_volume_half_up_deterministically() -> None:
    merge = _versioned(
        replace(
            _SPLIT_ACTION,
            action_type=CorporateActionType.REVERSE_SPLIT,
            ex_date=None,
            effective_date=date(2026, 8, 5),
            share_multiplier=Decimal("0.5"),
        )
    )
    bars = tuple(
        _bar(day, volume=101) if day < date(2026, 8, 5) else _bar(day) for day in _OPEN_DATES
    )

    plan = _plan(AdjustmentMethod.SPLIT_ADJUSTED, bars, (merge,))

    by_date = {item.source.trading_date: item for item in plan.adjusted_bars}
    assert by_date[date(2026, 8, 4)].close_price == Decimal("2000.00000000")
    assert by_date[date(2026, 8, 4)].volume == 51
    assert by_date[date(2026, 8, 5)].volume == 100


def test_cash_dividend_only_affects_total_return_prices() -> None:
    dividend = _versioned(_dividend(Decimal(50), record_date=date(2026, 8, 6)))

    split_adjusted = _plan(AdjustmentMethod.SPLIT_ADJUSTED, _bars(), (dividend,))
    total_return = _plan(AdjustmentMethod.TOTAL_RETURN, _bars(), (dividend,))

    assert split_adjusted.applied_actions == ()
    assert {item.price_factor for item in split_adjusted.adjusted_bars} == {
        Decimal("1.0000000000000000")
    }
    assert len(total_return.applied_actions) == 1
    assert total_return.applied_actions[0].price_factor == Decimal("0.9500000000000000")
    assert total_return.applied_actions[0].volume_factor == Decimal("1.0000000000000000")
    by_date = {item.source.trading_date: item for item in total_return.adjusted_bars}
    assert by_date[date(2026, 8, 4)].close_price == Decimal("950.00000000")
    assert by_date[date(2026, 8, 4)].volume == 100
    assert by_date[date(2026, 8, 5)].close_price == Decimal("1000.00000000")


def test_stock_dividend_changes_shares_in_both_methods() -> None:
    stock_dividend = _versioned(
        replace(
            _SPLIT_ACTION,
            action_type=CorporateActionType.STOCK_DIVIDEND,
            ex_date=date(2026, 8, 6),
            share_multiplier=Decimal("1.25"),
        )
    )

    plan = _plan(AdjustmentMethod.TOTAL_RETURN, _bars(), (stock_dividend,))

    by_date = {item.source.trading_date: item for item in plan.adjusted_bars}
    assert by_date[date(2026, 8, 5)].close_price == Decimal("800.00000000")
    assert by_date[date(2026, 8, 5)].volume == 125


def test_cancelled_actions_are_excluded_from_factors() -> None:
    cancelled = _versioned(replace(_SPLIT_ACTION, lifecycle=CorporateActionLifecycle.CANCELLED))

    plan = _plan(AdjustmentMethod.SPLIT_ADJUSTED, _bars(), (cancelled,))

    assert plan.applied_actions == ()


def test_cash_dividend_without_ex_date_blocks_generation() -> None:
    pending = _versioned(
        _dividend(
            Decimal(50),
            ex_date=None,
            record_date=date(2026, 8, 6),
            quality=CorporateActionQuality.PENDING,
        )
    )

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.SPLIT_ADJUSTED, _bars(), (pending,))

    assert error.value.failure is AdjustmentFailure.MISSING_CONDITIONS


def test_conflicting_action_blocks_generation() -> None:
    conflicted = _versioned(_dividend(Decimal(50), quality=CorporateActionQuality.CONFLICT))

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.TOTAL_RETURN, _bars(), (conflicted,))

    assert error.value.failure is AdjustmentFailure.CONFLICTING_ACTION


def test_unsupported_merger_in_range_blocks_generation() -> None:
    merger = _versioned(
        replace(
            _SPLIT_ACTION,
            action_type=CorporateActionType.MERGER,
            ex_date=None,
            effective_date=date(2026, 8, 6),
            share_multiplier=None,
            quality=CorporateActionQuality.UNSUPPORTED,
        )
    )

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.SPLIT_ADJUSTED, _bars(), (merger,))

    assert error.value.failure is AdjustmentFailure.UNSUPPORTED_ACTION


def test_unconfirmed_bar_blocks_generation() -> None:
    bars = tuple(
        _bar(
            day,
            finality=(BarFinality.PENDING if day == date(2026, 8, 5) else BarFinality.CONFIRMED),
        )
        for day in _OPEN_DATES
    )

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.SPLIT_ADJUSTED, bars, ())

    assert error.value.failure is AdjustmentFailure.UNCONFIRMED_BAR


def test_unexplained_missing_bar_blocks_generation() -> None:
    bars = tuple(_bar(day) for day in _OPEN_DATES if day != date(2026, 8, 5))

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.SPLIT_ADJUSTED, bars, ())

    assert error.value.failure is AdjustmentFailure.MISSING_BAR


def test_missing_bars_before_listing_are_explained_gaps() -> None:
    listed_on = date(2026, 8, 5)
    bars = tuple(_bar(day) for day in _OPEN_DATES if day >= listed_on)

    plan = _plan(AdjustmentMethod.SPLIT_ADJUSTED, bars, (), listed_on=listed_on)

    assert tuple(item.source.trading_date for item in plan.adjusted_bars) == _OPEN_DATES[2:]


def test_cash_event_without_prior_close_blocks_generation() -> None:
    listed_on = date(2026, 8, 5)
    bars = tuple(_bar(day) for day in _OPEN_DATES if day >= listed_on)
    dividend = _versioned(_dividend(Decimal(50)))

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.TOTAL_RETURN, bars, (dividend,), listed_on=listed_on)

    assert error.value.failure is AdjustmentFailure.MISSING_PRIOR_CLOSE


def test_same_day_share_change_and_cash_dividend_blocks_generation() -> None:
    split = _versioned(_SPLIT_ACTION)
    dividend = _versioned(_dividend(Decimal(50)))

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.TOTAL_RETURN, _bars(), (split, dividend))

    assert error.value.failure is AdjustmentFailure.MIXED_SAME_DAY_BASIS


def test_dividend_larger_than_prior_close_blocks_generation() -> None:
    dividend = _versioned(_dividend(Decimal(1000)))

    with pytest.raises(AdjustmentError) as error:
        _ = _plan(AdjustmentMethod.TOTAL_RETURN, _bars(), (dividend,))

    assert error.value.failure is AdjustmentFailure.INVALID_CASH_FACTOR
