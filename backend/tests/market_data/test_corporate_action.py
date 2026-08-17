from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionInvariant,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    InvalidCorporateActionError,
    TimePrecision,
    validate_corporate_action,
)


def _stock_split() -> CorporateAction:
    return CorporateAction(
        action_type=CorporateActionType.STOCK_SPLIT,
        lifecycle=CorporateActionLifecycle.ANNOUNCED,
        quality=CorporateActionQuality.PENDING,
        announced_at=None,
        announcement_date=date(2026, 7, 1),
        time_precision=TimePrecision.DATE,
        ex_date=date(2026, 8, 3),
        effective_date=date(2026, 8, 3),
        record_date=None,
        payment_date=None,
        share_multiplier=Decimal(5),
        cash_amount=None,
        currency=None,
        subscription_price=None,
        related_instrument_id=None,
        source="DART",
        source_event_id="20260701000001",
        source_reference="https://dart.fss.or.kr/report/20260701000001",
        available_at=datetime(2026, 7, 2, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 16, 1, 0, tzinfo=UTC),
    )


def test_valid_corporate_action_passes_validation() -> None:
    validate_corporate_action(_stock_split())


def test_non_positive_share_multiplier_is_rejected() -> None:
    action = replace(_stock_split(), share_multiplier=Decimal(0))

    with pytest.raises(InvalidCorporateActionError) as error:
        validate_corporate_action(action)

    assert error.value.invariant == CorporateActionInvariant.SHARE_MULTIPLIER


def test_negative_cash_amount_is_rejected() -> None:
    action = replace(
        _stock_split(),
        action_type=CorporateActionType.CASH_DIVIDEND,
        share_multiplier=None,
        cash_amount=Decimal(-1),
        currency="KRW",
    )

    with pytest.raises(InvalidCorporateActionError) as error:
        validate_corporate_action(action)

    assert error.value.invariant == CorporateActionInvariant.AMOUNTS


def test_negative_subscription_price_is_rejected() -> None:
    action = replace(
        _stock_split(),
        action_type=CorporateActionType.RIGHTS_ISSUE,
        subscription_price=Decimal(-1),
    )

    with pytest.raises(InvalidCorporateActionError) as error:
        validate_corporate_action(action)

    assert error.value.invariant == CorporateActionInvariant.AMOUNTS


def test_date_precision_forbids_announced_time() -> None:
    action = replace(
        _stock_split(),
        announced_at=datetime(2026, 7, 1, 8, 30, tzinfo=UTC),
        time_precision=TimePrecision.DATE,
    )

    with pytest.raises(InvalidCorporateActionError) as error:
        validate_corporate_action(action)

    assert error.value.invariant == CorporateActionInvariant.TIME_PRECISION


def test_minute_precision_requires_announced_time() -> None:
    action = replace(_stock_split(), announced_at=None, time_precision=TimePrecision.MINUTE)

    with pytest.raises(InvalidCorporateActionError) as error:
        validate_corporate_action(action)

    assert error.value.invariant == CorporateActionInvariant.TIME_PRECISION
