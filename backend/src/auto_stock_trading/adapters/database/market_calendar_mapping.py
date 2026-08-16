from typing import TYPE_CHECKING, assert_never
from uuid import uuid4

from auto_stock_trading.adapters.database.market_calendar_rows import MarketCalendarRow
from auto_stock_trading.domain.market_data.calendar import (
    CalendarInvariant,
    CalendarObservation,
    CalendarSessionKey,
    CalendarSource,
    CalendarVerification,
    CalendarVerificationState,
    ClosedMarketSession,
    ConfirmedVerification,
    ConflictingVerification,
    InvalidMarketCalendarError,
    MarketCalendarRecord,
    MarketSession,
    MarketSessionStatus,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
    ShortenedMarketSession,
    calendar_confirmed_at,
    calendar_session_key,
    calendar_session_reason,
    calendar_session_status,
    calendar_session_window,
    calendar_verification_state,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


def new_calendar_row(
    observation: CalendarObservation,
    raw_response_id: UUID,
    version: int,
) -> MarketCalendarRow:
    key = calendar_session_key(observation.session)
    window = calendar_session_window(observation.session)
    received_at = observation.raw_response.received_at
    return MarketCalendarRow(
        id=uuid4(),
        country=key.country,
        exchange=key.exchange,
        trading_date=key.trading_date,
        session_type=key.session_type.value,
        session_status=calendar_session_status(observation.session).value,
        opens_at=window.opens_at if window is not None else None,
        closes_at=window.closes_at if window is not None else None,
        exchange_timezone=observation.exchange_timezone,
        reason=calendar_session_reason(observation.session),
        source=observation.source.name,
        source_reference=observation.source.reference,
        source_as_of=observation.source.as_of,
        received_at=received_at,
        verification_state=calendar_verification_state(observation.verification).value,
        confirmed_at=calendar_confirmed_at(observation.verification),
        version=version,
        valid_from=received_at,
        superseded_at=None,
        raw_response_id=raw_response_id,
        created_at=received_at,
        updated_at=received_at,
    )


def calendar_record(row: MarketCalendarRow) -> MarketCalendarRecord:
    return MarketCalendarRecord(
        id=row.id,
        session=_session_from_row(row),
        exchange_timezone=row.exchange_timezone,
        source=CalendarSource(row.source, row.source_reference, row.source_as_of),
        received_at=row.received_at,
        verification=_verification_from_row(row),
        version=row.version,
        valid_from=row.valid_from,
        superseded_at=row.superseded_at,
        raw_response_id=row.raw_response_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def calendar_facts_match(
    row: MarketCalendarRow,
    observation: CalendarObservation,
) -> bool:
    key = calendar_session_key(observation.session)
    window = calendar_session_window(observation.session)
    return (
        row.country == key.country
        and row.exchange == key.exchange
        and row.trading_date == key.trading_date
        and row.session_type == key.session_type.value
        and row.session_status == calendar_session_status(observation.session).value
        and row.opens_at == (window.opens_at if window is not None else None)
        and row.closes_at == (window.closes_at if window is not None else None)
        and row.exchange_timezone == observation.exchange_timezone
        and row.reason == calendar_session_reason(observation.session)
    )


def refresh_calendar_from_primary(
    row: MarketCalendarRow,
    observation: CalendarObservation,
    raw_response_id: UUID,
) -> None:
    row.source = observation.source.name
    row.source_reference = observation.source.reference
    row.source_as_of = observation.source.as_of
    if isinstance(observation.verification, PendingVerification):
        _refresh_raw_evidence(row, observation, raw_response_id)
    else:
        _refresh_calendar_evidence(row, observation, raw_response_id)


def refresh_calendar_from_secondary(
    row: MarketCalendarRow,
    observation: CalendarObservation,
    raw_response_id: UUID,
) -> None:
    _refresh_calendar_evidence(row, observation, raw_response_id)


def mark_calendar_conflict(
    row: MarketCalendarRow,
    observation: CalendarObservation,
    raw_response_id: UUID,
) -> None:
    received_at = observation.raw_response.received_at
    row.received_at = received_at
    row.verification_state = CalendarVerificationState.CONFLICT.value
    row.confirmed_at = None
    row.raw_response_id = raw_response_id
    row.updated_at = received_at


def supersede_calendar(row: MarketCalendarRow, superseded_at: datetime) -> None:
    row.superseded_at = superseded_at
    row.updated_at = superseded_at


def _refresh_calendar_evidence(
    row: MarketCalendarRow,
    observation: CalendarObservation,
    raw_response_id: UUID,
) -> None:
    _refresh_raw_evidence(row, observation, raw_response_id)
    row.verification_state = calendar_verification_state(observation.verification).value
    row.confirmed_at = calendar_confirmed_at(observation.verification)


def _refresh_raw_evidence(
    row: MarketCalendarRow,
    observation: CalendarObservation,
    raw_response_id: UUID,
) -> None:
    received_at = observation.raw_response.received_at
    row.received_at = received_at
    row.raw_response_id = raw_response_id
    row.updated_at = received_at


def _session_from_row(row: MarketCalendarRow) -> MarketSession:
    key = CalendarSessionKey(
        row.country,
        row.exchange,
        row.trading_date,
        MarketSessionType(row.session_type),
    )
    status = MarketSessionStatus(row.session_status)
    match status:
        case MarketSessionStatus.OPEN:
            return OpenMarketSession(key, _window_from_row(row))
        case MarketSessionStatus.CLOSED:
            if row.opens_at is not None or row.closes_at is not None:
                raise InvalidMarketCalendarError(CalendarInvariant.SESSION_WINDOW)
            return ClosedMarketSession(key, row.reason)
        case MarketSessionStatus.SHORTENED:
            return ShortenedMarketSession(key, _window_from_row(row), row.reason)
    assert_never(status)


def _window_from_row(row: MarketCalendarRow) -> SessionWindow:
    if row.opens_at is None or row.closes_at is None:
        raise InvalidMarketCalendarError(CalendarInvariant.SESSION_WINDOW)
    return SessionWindow(row.opens_at, row.closes_at)


def _verification_from_row(row: MarketCalendarRow) -> CalendarVerification:
    state = CalendarVerificationState(row.verification_state)
    match state:
        case CalendarVerificationState.PENDING:
            _require_empty_confirmation(row)
            return PendingVerification()
        case CalendarVerificationState.CONFIRMED:
            if row.confirmed_at is None:
                raise InvalidMarketCalendarError(CalendarInvariant.CONFIRMATION)
            return ConfirmedVerification(row.confirmed_at)
        case CalendarVerificationState.CONFLICT:
            _require_empty_confirmation(row)
            return ConflictingVerification()
    assert_never(state)


def _require_empty_confirmation(row: MarketCalendarRow) -> None:
    if row.confirmed_at is not None:
        raise InvalidMarketCalendarError(CalendarInvariant.CONFIRMATION)
