from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID


class CorporateActionType(StrEnum):
    STOCK_SPLIT = "stock_split"
    REVERSE_SPLIT = "reverse_split"
    STOCK_DIVIDEND = "stock_dividend"
    CASH_DIVIDEND = "cash_dividend"
    ETF_DISTRIBUTION = "etf_distribution"
    RIGHTS_ISSUE = "rights_issue"
    CAPITAL_REDUCTION = "capital_reduction"
    MERGER = "merger"
    SPIN_OFF = "spin_off"
    TRADING_SUSPENSION = "trading_suspension"
    DELISTING = "delisting"


class CorporateActionLifecycle(StrEnum):
    ANNOUNCED = "announced"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CorporateActionQuality(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"


class TimePrecision(StrEnum):
    DATE = "date"
    MINUTE = "minute"
    SECOND = "second"


class CorporateActionInvariant(StrEnum):
    SHARE_MULTIPLIER = "corporate action share multiplier must be positive"
    AMOUNTS = "corporate action cash amounts must not be negative"
    TIME_PRECISION = "announced_at must match the declared time precision"
    VALIDITY = "corrected corporate action evidence must be newer than the current version"


@dataclass(frozen=True, slots=True)
class InvalidCorporateActionError(Exception):
    invariant: CorporateActionInvariant

    @override
    def __str__(self) -> str:
        return self.invariant.value


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_type: CorporateActionType
    lifecycle: CorporateActionLifecycle
    quality: CorporateActionQuality
    announced_at: datetime | None
    announcement_date: date
    time_precision: TimePrecision
    ex_date: date | None
    effective_date: date | None
    record_date: date | None
    payment_date: date | None
    share_multiplier: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    subscription_price: Decimal | None
    related_instrument_id: UUID | None
    source: str
    source_event_id: str
    source_reference: str
    available_at: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class CorporateActionRawResponse:
    endpoint: str
    request_fingerprint: str
    received_at: datetime
    payload_json: str


@dataclass(frozen=True, slots=True)
class CorporateActionObservation:
    action: CorporateAction
    raw_response: CorporateActionRawResponse


@dataclass(frozen=True, slots=True)
class CorporateActionBundle:
    source: str
    symbol: str
    observations: tuple[CorporateActionObservation, ...]
    supporting_raw_responses: tuple[CorporateActionRawResponse, ...]
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedCorporateAction:
    action: CorporateAction
    corporate_action_id: UUID
    action_key: UUID
    version: int
    valid_from: datetime
    superseded_at: datetime | None


def validate_corporate_action(action: CorporateAction) -> None:
    if action.share_multiplier is not None and action.share_multiplier <= 0:
        raise InvalidCorporateActionError(CorporateActionInvariant.SHARE_MULTIPLIER)
    for amount in (action.cash_amount, action.subscription_price):
        if amount is not None and amount < 0:
            raise InvalidCorporateActionError(CorporateActionInvariant.AMOUNTS)
    timeless = action.announced_at is None
    if timeless != (action.time_precision == TimePrecision.DATE):
        raise InvalidCorporateActionError(CorporateActionInvariant.TIME_PRECISION)
