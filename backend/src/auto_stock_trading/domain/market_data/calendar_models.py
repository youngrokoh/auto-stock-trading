from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, assert_never, override
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID


class MarketSessionType(StrEnum):
    REGULAR = "regular"


class MarketSessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SHORTENED = "shortened"


class CalendarVerificationState(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"


class CalendarScheduleDecision(StrEnum):
    ALLOWED = "allowed"
    MISSING = "missing"
    PENDING = "pending"
    CONFLICT = "conflict"
    STALE = "stale"
    CLOSED = "closed"
    OUTSIDE_SESSION = "outside_session"


class CalendarInvariant(StrEnum):
    AWARE_TIME = "calendar timestamps must include a timezone"
    WINDOW_ORDER = "market session must open before it closes"
    SESSION_WINDOW = "market session status and timestamps are inconsistent"
    CONFIRMATION = "calendar confirmation state and timestamp are inconsistent"
    EXCHANGE_TIMEZONE = "exchange timezone is invalid"
    SESSION_DATE = "market session timestamps must fall on the trading date"
    SESSION_STATUS = "market session status must agree with the normal session window"
    DATE_RANGE = "market calendar range must start on or before it ends"
    VERSION = "market calendar version must be positive"
    VALIDITY = "superseded time must be after valid time"


@dataclass(frozen=True, slots=True)
class InvalidMarketCalendarError(Exception):
    invariant: CalendarInvariant

    @override
    def __str__(self) -> str:
        return self.invariant.value


@dataclass(frozen=True, slots=True)
class CalendarSessionKey:
    country: str
    exchange: str
    trading_date: date
    session_type: MarketSessionType


@dataclass(frozen=True, slots=True)
class CalendarSessionRange:
    country: str
    exchange: str
    start_date: date
    end_date: date
    session_type: MarketSessionType = MarketSessionType.REGULAR

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise InvalidMarketCalendarError(CalendarInvariant.DATE_RANGE)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.opens_at)
        require_aware(self.closes_at)
        if self.opens_at >= self.closes_at:
            raise InvalidMarketCalendarError(CalendarInvariant.WINDOW_ORDER)


@dataclass(frozen=True, slots=True)
class OpenMarketSession:
    key: CalendarSessionKey
    window: SessionWindow


@dataclass(frozen=True, slots=True)
class ClosedMarketSession:
    key: CalendarSessionKey
    reason: str | None


@dataclass(frozen=True, slots=True)
class ShortenedMarketSession:
    key: CalendarSessionKey
    window: SessionWindow
    reason: str | None


type MarketSession = OpenMarketSession | ClosedMarketSession | ShortenedMarketSession


@dataclass(frozen=True, slots=True)
class CalendarSource:
    name: str
    reference: str
    as_of: date


@dataclass(frozen=True, slots=True)
class CalendarRawResponse:
    endpoint: str
    request_fingerprint: str
    received_at: datetime
    payload_json: str

    def __post_init__(self) -> None:
        require_aware(self.received_at)


@dataclass(frozen=True, slots=True)
class PendingVerification:
    pass


@dataclass(frozen=True, slots=True)
class ConfirmedVerification:
    confirmed_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.confirmed_at)


@dataclass(frozen=True, slots=True)
class ConflictingVerification:
    pass


type CalendarVerification = PendingVerification | ConfirmedVerification | ConflictingVerification


@dataclass(frozen=True, slots=True)
class CalendarObservation:
    session: MarketSession
    exchange_timezone: str
    source: CalendarSource
    raw_response: CalendarRawResponse
    verification: CalendarVerification

    def __post_init__(self) -> None:
        _validate_session_date(self.session, self.exchange_timezone)


@dataclass(frozen=True, slots=True)
class MarketCalendarRecord:
    id: UUID
    session: MarketSession
    exchange_timezone: str
    source: CalendarSource
    received_at: datetime
    verification: CalendarVerification
    version: int
    valid_from: datetime
    superseded_at: datetime | None
    raw_response_id: UUID
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for timestamp in (
            self.received_at,
            self.valid_from,
            self.created_at,
            self.updated_at,
        ):
            require_aware(timestamp)
        if self.superseded_at is not None:
            require_aware(self.superseded_at)
            if self.superseded_at <= self.valid_from:
                raise InvalidMarketCalendarError(CalendarInvariant.VALIDITY)
        if self.version < 1:
            raise InvalidMarketCalendarError(CalendarInvariant.VERSION)
        _validate_session_date(self.session, self.exchange_timezone)


def _validate_session_date(session: MarketSession, exchange_timezone: str) -> None:
    window = _session_window(session)
    if window is None:
        return
    timezone = parse_exchange_timezone(exchange_timezone)
    trading_date = _session_key(session).trading_date
    opens_at = window.opens_at.astimezone(timezone)
    closes_at = window.closes_at.astimezone(timezone)
    if opens_at.date() != trading_date or closes_at.date() != trading_date:
        raise InvalidMarketCalendarError(CalendarInvariant.SESSION_DATE)
    _validate_session_status(session, opens_at, closes_at)


def _validate_session_status(
    session: MarketSession,
    opens_at: datetime,
    closes_at: datetime,
) -> None:
    is_normal_window = (opens_at.hour, opens_at.minute, opens_at.second, opens_at.microsecond) == (
        9,
        0,
        0,
        0,
    ) and (closes_at.hour, closes_at.minute, closes_at.second, closes_at.microsecond) == (
        15,
        30,
        0,
        0,
    )
    match session:
        case OpenMarketSession() if not is_normal_window:
            raise InvalidMarketCalendarError(CalendarInvariant.SESSION_STATUS)
        case ShortenedMarketSession() if is_normal_window:
            raise InvalidMarketCalendarError(CalendarInvariant.SESSION_STATUS)
        case OpenMarketSession() | ClosedMarketSession() | ShortenedMarketSession():
            return
    assert_never(session)


def _session_key(session: MarketSession) -> CalendarSessionKey:
    match session:
        case OpenMarketSession(key=key) | ClosedMarketSession(key=key):
            return key
        case ShortenedMarketSession(key=key):
            return key
    assert_never(session)


def _session_window(session: MarketSession) -> SessionWindow | None:
    match session:
        case OpenMarketSession(window=window) | ShortenedMarketSession(window=window):
            return window
        case ClosedMarketSession():
            return None
    assert_never(session)


def parse_exchange_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise InvalidMarketCalendarError(CalendarInvariant.EXCHANGE_TIMEZONE) from error


def require_aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise InvalidMarketCalendarError(CalendarInvariant.AWARE_TIME)
