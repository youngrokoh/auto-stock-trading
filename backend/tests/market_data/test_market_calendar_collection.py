from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.application.market_calendar import (
    KisCalendarConfirmer,
    KrxCalendarCollector,
    MissingPrimaryCalendarError,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarRawResponse,
    CalendarSessionKey,
    CalendarSessionRange,
    CalendarSource,
    ConfirmedVerification,
    MarketCalendarRecord,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
)

_SEOUL = ZoneInfo("Asia/Seoul")
_TRADING_DATE = date(2026, 8, 18)
_STARTED_AT = datetime(2026, 8, 17, 21, 30, tzinfo=UTC)


@dataclass(slots=True)
class FixtureSource:
    observations: tuple[CalendarObservation, ...]
    calls: list[CalendarSessionRange] = field(default_factory=list)

    async def fetch_sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]:
        self.calls.append(query)
        return self.observations

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class FixtureVerifier:
    observation: CalendarObservation
    calls: list[MarketCalendarRecord] = field(default_factory=list)

    async def verify(self, current: MarketCalendarRecord) -> CalendarObservation:
        self.calls.append(current)
        return self.observation

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class FixtureStore:
    current: MarketCalendarRecord | None = None
    saved_batches: list[tuple[CalendarObservation, ...]] = field(default_factory=list)
    events: list[tuple[str, str, str]] = field(default_factory=list)

    async def save_all(
        self,
        observations: tuple[CalendarObservation, ...],
    ) -> tuple[MarketCalendarRecord, ...]:
        self.saved_batches.append(observations)
        records = tuple(_record(item) for item in observations)
        if records:
            self.current = records[-1]
        return records

    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None:
        _ = key
        return self.current

    async def mark_sync_started(
        self,
        source: str,
        target: str,
        started_at: datetime,
    ) -> None:
        _ = started_at
        self.events.append(("started", source, target))

    async def mark_sync_succeeded(
        self,
        source: str,
        target: str,
        completed_at: datetime,
    ) -> None:
        _ = completed_at
        self.events.append(("succeeded", source, target))

    async def mark_sync_failed(
        self,
        source: str,
        target: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        _ = (failed_at, error_message)
        self.events.append((error_code, source, target))

    async def close(self) -> None:
        return None


def test_krx_collector_saves_the_range_as_one_batch_and_records_success() -> None:
    query = CalendarSessionRange("KR", "XKRX", _TRADING_DATE, _TRADING_DATE)
    observation = _observation(PendingVerification())
    source = FixtureSource((observation,))
    store = FixtureStore()
    collector = KrxCalendarCollector(source, store)

    records = anyio.run(collector.collect, query, _STARTED_AT)

    assert source.calls == [query]
    assert store.saved_batches == [(observation,)]
    assert len(records) == 1
    assert store.events == [
        ("started", "KRX", "XKRX:2026-2026"),
        ("succeeded", "KRX", "XKRX:2026-2026"),
    ]


def test_kis_confirmer_fails_closed_when_the_krx_session_is_missing() -> None:
    key = _key()
    verifier = FixtureVerifier(_observation(ConfirmedVerification(_STARTED_AT)))
    store = FixtureStore()
    confirmer = KisCalendarConfirmer(verifier, store)

    with pytest.raises(MissingPrimaryCalendarError):
        _ = anyio.run(confirmer.confirm, key, _STARTED_AT)

    assert verifier.calls == []
    assert store.saved_batches == []
    assert store.events == [
        ("started", "KIS", "XKRX:2026-08-18"),
        ("MissingPrimaryCalendarError", "KIS", "XKRX:2026-08-18"),
    ]


def _observation(
    verification: PendingVerification | ConfirmedVerification,
) -> CalendarObservation:
    return CalendarObservation(
        session=OpenMarketSession(_key(), _window()),
        exchange_timezone="Asia/Seoul",
        source=CalendarSource(
            "KRX" if isinstance(verification, PendingVerification) else "KIS",
            "fixture",
            _TRADING_DATE,
        ),
        raw_response=CalendarRawResponse(
            endpoint="fixture://market-calendar",
            request_fingerprint=f"fixture:{type(verification).__name__}",
            received_at=_STARTED_AT,
            payload_json='{"fixture":true}',
        ),
        verification=verification,
    )


def _record(observation: CalendarObservation) -> MarketCalendarRecord:
    return MarketCalendarRecord(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        session=observation.session,
        exchange_timezone=observation.exchange_timezone,
        source=observation.source,
        received_at=observation.raw_response.received_at,
        verification=observation.verification,
        version=1,
        valid_from=observation.raw_response.received_at,
        superseded_at=None,
        raw_response_id=UUID("00000000-0000-0000-0000-000000000002"),
        created_at=observation.raw_response.received_at,
        updated_at=observation.raw_response.received_at,
    )


def _key() -> CalendarSessionKey:
    return CalendarSessionKey("KR", "XKRX", _TRADING_DATE, MarketSessionType.REGULAR)


def _window() -> SessionWindow:
    return SessionWindow(
        datetime.combine(_TRADING_DATE, time(9), _SEOUL).astimezone(UTC),
        datetime.combine(_TRADING_DATE, time(15, 30), _SEOUL).astimezone(UTC),
    )
