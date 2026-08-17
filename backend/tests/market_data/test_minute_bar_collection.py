from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import final
from uuid import uuid4
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.application.minute_bars import (
    MinuteBarCollectionError,
    MinuteBarCollectionFailure,
    MinuteBarCollector,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarSource,
    ClosedMarketSession,
    ConflictingVerification,
    MarketCalendarRecord,
    MarketSessionType,
    OpenMarketSession,
    PendingVerification,
    SessionWindow,
)
from auto_stock_trading.domain.market_data.minute_bars import (
    MinuteBar,
    MinuteBarBundle,
    MinuteBarPage,
    VersionedMinuteBar,
)
from auto_stock_trading.domain.market_data.models import (
    BarFinality,
    BrokerOperation,
    InstrumentTarget,
    ProductType,
    RawBrokerResponse,
)

_SEOUL = ZoneInfo("Asia/Seoul")
_TARGET = InstrumentTarget("069500", ProductType.ETF)
_HOLIDAY = date(2026, 8, 17)
_TRADING_DATE = date(2026, 8, 14)
_MINUTE = timedelta(minutes=1)
_NOW = datetime(2026, 8, 17, 5, 0, tzinfo=UTC)


def _window(day: date) -> SessionWindow:
    return SessionWindow(
        datetime.combine(day, time(9), _SEOUL).astimezone(UTC),
        datetime.combine(day, time(15, 30), _SEOUL).astimezone(UTC),
    )


def _record(
    day: date,
    *,
    is_open: bool = True,
    conflict: bool = False,
) -> MarketCalendarRecord:
    key = CalendarSessionKey("KR", "XKRX", day, MarketSessionType.REGULAR)
    verification = ConflictingVerification() if conflict else PendingVerification()
    session = OpenMarketSession(key, _window(day)) if is_open else ClosedMarketSession(key, None)
    return MarketCalendarRecord(
        id=uuid4(),
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", "test", day),
        received_at=_NOW,
        verification=verification,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
        raw_response_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
    )


@final
@dataclass
class FakeCalendar:
    records: dict[date, MarketCalendarRecord]

    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None:
        return self.records.get(key.trading_date)

    async def previous_open_date(self, key: CalendarSessionKey) -> date | None:
        candidates = [
            day
            for day, record in self.records.items()
            if day < key.trading_date and isinstance(record.session, OpenMarketSession)
        ]
        return max(candidates) if candidates else None


def _bar(minute_offset: int, received_at: datetime) -> MinuteBar:
    started = _window(_TRADING_DATE).opens_at + minute_offset * _MINUTE
    return MinuteBar(
        symbol=_TARGET.symbol,
        trading_date=_TRADING_DATE,
        bar_started_at=started,
        open_price=Decimal(1000),
        high_price=Decimal(1010),
        low_price=Decimal(990),
        close_price=Decimal(1005),
        volume=100,
        cumulative_trading_value=Decimal(1_000_000),
        source="KIS",
        received_at=received_at,
    )


def _bundle(bars: tuple[MinuteBar, ...]) -> MinuteBarBundle:
    raw = RawBrokerResponse(
        operation=BrokerOperation.MINUTE_BARS,
        endpoint="/test",
        request_fingerprint="test:minute:page",
        received_at=_NOW,
        payload_json="{}",
    )
    return MinuteBarBundle(
        target=_TARGET,
        trading_date=_TRADING_DATE,
        pages=(MinuteBarPage(raw, bars),),
        collected_at=_NOW,
    )


@final
@dataclass
class FakeSource:
    bundle: MinuteBarBundle
    requests: list[tuple[date, SessionWindow]] = field(default_factory=list)

    async def fetch_minute_bars(
        self,
        target: InstrumentTarget,
        trading_date: date,
        window: SessionWindow,
        now: datetime,
    ) -> MinuteBarBundle:
        _ = (target, now)
        self.requests.append((trading_date, window))
        return self.bundle

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeStore:
    priors: tuple[VersionedMinuteBar, ...] = ()
    saved: list[MinuteBarBundle] = field(default_factory=list)
    confirmed_bars: list[MinuteBar] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    started: int = 0

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None:
        _ = (target, started_at)
        self.started += 1

    async def save_minute_bundle(self, bundle: MinuteBarBundle) -> None:
        self.saved.append(bundle)

    async def confirm_minute_bar(self, bar: MinuteBar, confirmed_at: datetime) -> bool:
        _ = confirmed_at
        self.confirmed_bars.append(bar)
        return True

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]:
        _ = (symbol, trading_date)
        return self.priors

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        _ = (target, failed_at, error_message)
        self.failures.append(error_code)

    async def close(self) -> None:
        return None


def _versioned(bar: MinuteBar) -> VersionedMinuteBar:
    return VersionedMinuteBar(
        bar=bar,
        finality=BarFinality.PENDING,
        confirmed_at=None,
        version=1,
        valid_from=bar.received_at,
        superseded_at=None,
    )


def test_holiday_collection_targets_previous_open_day_and_stays_pending() -> None:
    async def run() -> None:
        calendar = FakeCalendar(
            {_HOLIDAY: _record(_HOLIDAY, is_open=False), _TRADING_DATE: _record(_TRADING_DATE)}
        )
        bars = tuple(_bar(offset, _NOW) for offset in range(2))
        source = FakeSource(_bundle(bars))
        store = FakeStore()

        result = await MinuteBarCollector(calendar, source, store).collect(_TARGET, _NOW)

        assert result.trading_date == _TRADING_DATE
        assert result.collected == 2
        assert result.pending == 2
        assert result.confirmed == 0
        assert store.started == 1
        assert len(store.saved) == 1
        assert source.requests == [(_TRADING_DATE, _window(_TRADING_DATE))]

    anyio.run(run)


def test_recollection_confirms_matching_bars_after_the_interval() -> None:
    async def run() -> None:
        calendar = FakeCalendar(
            {_HOLIDAY: _record(_HOLIDAY, is_open=False), _TRADING_DATE: _record(_TRADING_DATE)}
        )
        earlier = _NOW - timedelta(hours=1)
        matching = _bar(0, earlier)
        changed_prior = replace(_bar(1, earlier), close_price=Decimal(1))
        source = FakeSource(_bundle((_bar(0, _NOW), _bar(1, _NOW))))
        store = FakeStore(priors=(_versioned(matching), _versioned(changed_prior)))

        result = await MinuteBarCollector(calendar, source, store).collect(_TARGET, _NOW)

        assert result.confirmed == 1
        assert result.pending == 1
        assert [bar.bar_started_at for bar in store.confirmed_bars] == [matching.bar_started_at]

    anyio.run(run)


def test_today_is_targeted_after_the_first_completed_minute() -> None:
    async def run() -> None:
        today = _TRADING_DATE
        now = _window(today).opens_at + timedelta(minutes=5)
        calendar = FakeCalendar({today: _record(today)})
        source = FakeSource(_bundle((_bar(0, now),)))
        store = FakeStore()

        result = await MinuteBarCollector(calendar, source, store).collect(_TARGET, now)

        assert result.trading_date == today
        assert source.requests == [(today, _window(today))]

    anyio.run(run)


def test_missing_or_conflicting_calendar_fails_closed() -> None:
    async def run() -> None:
        store = FakeStore()
        empty = MinuteBarCollector(FakeCalendar({}), FakeSource(_bundle(())), store)
        with pytest.raises(MinuteBarCollectionError) as missing:
            _ = await empty.collect(_TARGET, _NOW)

        conflicted_calendar = FakeCalendar({_HOLIDAY: _record(_HOLIDAY, conflict=True)})
        conflicted = MinuteBarCollector(conflicted_calendar, FakeSource(_bundle(())), store)
        with pytest.raises(MinuteBarCollectionError) as conflict:
            _ = await conflicted.collect(_TARGET, _NOW)

        assert missing.value.failure is MinuteBarCollectionFailure.CALENDAR_COVERAGE
        assert conflict.value.failure is MinuteBarCollectionFailure.CALENDAR_CONFLICT
        assert store.failures == [
            MinuteBarCollectionFailure.CALENDAR_COVERAGE.value,
            MinuteBarCollectionFailure.CALENDAR_CONFLICT.value,
        ]
        assert store.saved == []

    anyio.run(run)


def test_empty_collection_fails_closed() -> None:
    async def run() -> None:
        calendar = FakeCalendar(
            {_HOLIDAY: _record(_HOLIDAY, is_open=False), _TRADING_DATE: _record(_TRADING_DATE)}
        )
        store = FakeStore()
        collector = MinuteBarCollector(calendar, FakeSource(_bundle(())), store)

        with pytest.raises(MinuteBarCollectionError) as error:
            _ = await collector.collect(_TARGET, _NOW)

        assert error.value.failure is MinuteBarCollectionFailure.EMPTY_COLLECTION
        assert store.failures == [MinuteBarCollectionFailure.EMPTY_COLLECTION.value]
        assert store.saved == []

    anyio.run(run)
