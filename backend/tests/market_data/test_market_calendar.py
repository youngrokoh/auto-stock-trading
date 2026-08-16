from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from auto_stock_trading.domain.market_data.calendar import (
    CalendarInvariant,
    CalendarObservation,
    CalendarRawResponse,
    CalendarScheduleDecision,
    CalendarSessionKey,
    CalendarSource,
    ClosedMarketSession,
    ConfirmedVerification,
    ConflictingVerification,
    InvalidMarketCalendarError,
    MarketCalendarRecord,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
    ShortenedMarketSession,
    calendar_schedule_decision,
)

_TRADING_DATE = date(2026, 8, 17)
_OPEN_AT = datetime(2026, 8, 17, 0, tzinfo=UTC)
_CLOSE_AT = datetime(2026, 8, 17, 6, 30, tzinfo=UTC)
_CONFIRMED_AT = datetime(2026, 8, 16, 22, tzinfo=UTC)
_SESSION_KEY = CalendarSessionKey(
    "KR",
    "XKRX",
    _TRADING_DATE,
    MarketSessionType.REGULAR,
)


def test_session_window_rejects_reverse_time_range() -> None:
    # Given
    closes_at = datetime(2026, 8, 17, 0, tzinfo=UTC)
    opens_at = datetime(2026, 8, 17, 1, tzinfo=UTC)

    # When / Then
    with pytest.raises(InvalidMarketCalendarError) as error:
        _ = SessionWindow(opens_at, closes_at)

    assert error.value.invariant is CalendarInvariant.WINDOW_ORDER


def test_observation_rejects_session_window_outside_trading_date() -> None:
    # Given
    session = OpenMarketSession(
        _session_key(),
        SessionWindow(
            datetime(2026, 8, 16, 0, tzinfo=UTC),
            datetime(2026, 8, 16, 6, 30, tzinfo=UTC),
        ),
    )

    # When / Then
    with pytest.raises(InvalidMarketCalendarError) as error:
        _ = CalendarObservation(
            session=session,
            exchange_timezone="Asia/Seoul",
            source=_source(),
            raw_response=_raw_response(),
            verification=PendingVerification(),
        )

    assert error.value.invariant is CalendarInvariant.SESSION_DATE


@pytest.mark.parametrize(
    "session",
    [
        OpenMarketSession(
            _SESSION_KEY,
            SessionWindow(
                datetime(2026, 8, 17, 1, tzinfo=UTC),
                _CLOSE_AT,
            ),
        ),
        ShortenedMarketSession(
            _SESSION_KEY,
            SessionWindow(_OPEN_AT, _CLOSE_AT),
            "fixture invalid shortened session",
        ),
    ],
)
def test_observation_rejects_session_status_that_disagrees_with_normal_window(
    session: OpenMarketSession | ShortenedMarketSession,
) -> None:
    # Given / When / Then
    with pytest.raises(InvalidMarketCalendarError) as error:
        _ = CalendarObservation(
            session=session,
            exchange_timezone="Asia/Seoul",
            source=_source(),
            raw_response=_raw_response(),
            verification=PendingVerification(),
        )

    assert error.value.invariant is CalendarInvariant.SESSION_STATUS


def _session_key() -> CalendarSessionKey:
    return _SESSION_KEY


def _source() -> CalendarSource:
    return CalendarSource("KRX", "fixture-calendar", date(2026, 8, 16))


def _raw_response() -> CalendarRawResponse:
    return CalendarRawResponse(
        endpoint="fixture://market-calendar",
        request_fingerprint="fixture:market-calendar:2026-08-17",
        received_at=datetime(2026, 8, 16, 21, 30, tzinfo=UTC),
        payload_json='{"fixture":true}',
    )


def _record(
    verification: PendingVerification | ConfirmedVerification | ConflictingVerification,
    *,
    closed: bool = False,
) -> MarketCalendarRecord:
    session = (
        ClosedMarketSession(_session_key(), "fixture holiday")
        if closed
        else OpenMarketSession(_session_key(), SessionWindow(_OPEN_AT, _CLOSE_AT))
    )
    observed_at = datetime(2026, 8, 16, 21, 30, tzinfo=UTC)
    return MarketCalendarRecord(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        session=session,
        exchange_timezone="Asia/Seoul",
        source=_source(),
        received_at=observed_at,
        verification=verification,
        version=1,
        valid_from=observed_at,
        superseded_at=None,
        raw_response_id=UUID("00000000-0000-0000-0000-000000000002"),
        created_at=observed_at,
        updated_at=observed_at,
    )


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (None, CalendarScheduleDecision.MISSING),
        (_record(PendingVerification()), CalendarScheduleDecision.PENDING),
        (_record(ConflictingVerification()), CalendarScheduleDecision.CONFLICT),
        (
            _record(ConfirmedVerification(datetime(2026, 8, 16, 10, tzinfo=UTC))),
            CalendarScheduleDecision.STALE,
        ),
        (
            _record(ConfirmedVerification(_CONFIRMED_AT), closed=True),
            CalendarScheduleDecision.CLOSED,
        ),
        (
            _record(ConfirmedVerification(_CONFIRMED_AT)),
            CalendarScheduleDecision.ALLOWED,
        ),
    ],
)
def test_calendar_schedule_decision_is_fail_closed(
    record: MarketCalendarRecord | None,
    expected: CalendarScheduleDecision,
) -> None:
    # Given
    decision_at = datetime(2026, 8, 17, 0, 5, tzinfo=UTC)

    # When
    decision = calendar_schedule_decision(record, decision_at)

    # Then
    assert decision is expected
