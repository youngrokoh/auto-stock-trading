from typing import TYPE_CHECKING, assert_never

from auto_stock_trading.domain.market_data.calendar_models import (
    CalendarScheduleDecision,
    CalendarSessionKey,
    CalendarVerification,
    CalendarVerificationState,
    ClosedMarketSession,
    ConfirmedVerification,
    ConflictingVerification,
    MarketCalendarRecord,
    MarketSession,
    MarketSessionStatus,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
    ShortenedMarketSession,
    parse_exchange_timezone,
    require_aware,
)

if TYPE_CHECKING:
    from datetime import datetime
    from zoneinfo import ZoneInfo


def calendar_schedule_decision(
    record: MarketCalendarRecord | None,
    decision_at: datetime,
) -> CalendarScheduleDecision:
    require_aware(decision_at)
    if record is None:
        return CalendarScheduleDecision.MISSING
    timezone = parse_exchange_timezone(record.exchange_timezone)
    verification_decision = _verification_schedule_decision(record, timezone)
    if verification_decision is not None:
        return verification_decision
    match record.session:
        case ClosedMarketSession():
            return CalendarScheduleDecision.CLOSED
        case OpenMarketSession(window=window) | ShortenedMarketSession(window=window):
            if window.opens_at <= decision_at <= window.closes_at:
                return CalendarScheduleDecision.ALLOWED
            return CalendarScheduleDecision.OUTSIDE_SESSION
    assert_never(record.session)


def calendar_session_key(session: MarketSession) -> CalendarSessionKey:
    match session:
        case OpenMarketSession(key=key) | ClosedMarketSession(key=key):
            return key
        case ShortenedMarketSession(key=key):
            return key
    assert_never(session)


def calendar_session_status(session: MarketSession) -> MarketSessionStatus:
    match session:
        case OpenMarketSession():
            return MarketSessionStatus.OPEN
        case ClosedMarketSession():
            return MarketSessionStatus.CLOSED
        case ShortenedMarketSession():
            return MarketSessionStatus.SHORTENED
    assert_never(session)


def calendar_session_window(session: MarketSession) -> SessionWindow | None:
    match session:
        case OpenMarketSession(window=window) | ShortenedMarketSession(window=window):
            return window
        case ClosedMarketSession():
            return None
    assert_never(session)


def calendar_session_reason(session: MarketSession) -> str | None:
    match session:
        case OpenMarketSession():
            return None
        case ClosedMarketSession(reason=reason) | ShortenedMarketSession(reason=reason):
            return reason
    assert_never(session)


def calendar_verification_state(
    verification: CalendarVerification,
) -> CalendarVerificationState:
    match verification:
        case PendingVerification():
            return CalendarVerificationState.PENDING
        case ConfirmedVerification():
            return CalendarVerificationState.CONFIRMED
        case ConflictingVerification():
            return CalendarVerificationState.CONFLICT
    assert_never(verification)


def calendar_confirmed_at(verification: CalendarVerification) -> datetime | None:
    match verification:
        case PendingVerification() | ConflictingVerification():
            return None
        case ConfirmedVerification(confirmed_at=confirmed_at):
            return confirmed_at
    assert_never(verification)


def _verification_schedule_decision(
    record: MarketCalendarRecord,
    timezone: ZoneInfo,
) -> CalendarScheduleDecision | None:
    match record.verification:
        case PendingVerification():
            return CalendarScheduleDecision.PENDING
        case ConflictingVerification():
            return CalendarScheduleDecision.CONFLICT
        case ConfirmedVerification(confirmed_at=confirmed_at):
            trading_date = calendar_session_key(record.session).trading_date
            return (
                CalendarScheduleDecision.STALE
                if confirmed_at.astimezone(timezone).date() != trading_date
                else None
            )
    assert_never(record.verification)
