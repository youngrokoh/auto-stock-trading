from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, override
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarVerificationState,
    MarketSessionStatus,
    MarketSessionType,
    calendar_session_status,
    calendar_session_window,
    calendar_verification_state,
)
from auto_stock_trading.domain.market_data.models import BarFinality

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.calendar import (
        MarketCalendarRecord,
        SessionWindow,
    )
    from auto_stock_trading.domain.market_data.minute_bars import (
        MinuteBar,
        MinuteBarBundle,
        VersionedMinuteBar,
    )
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_MINUTE: Final = timedelta(minutes=1)
_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"


class MinuteBarCollectionFailure(StrEnum):
    CALENDAR_COVERAGE = "calendar_coverage_missing"
    CALENDAR_CONFLICT = "calendar_conflict"
    EMPTY_COLLECTION = "minute_bars_missing"


@dataclass(frozen=True, slots=True)
class MinuteBarCollectionError(Exception):
    failure: MinuteBarCollectionFailure

    @override
    def __str__(self) -> str:
        return self.failure.value


class MinuteBarCalendar(Protocol):
    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None: ...

    async def previous_open_date(self, key: CalendarSessionKey) -> date | None: ...


class MinuteBarSource(Protocol):
    async def fetch_minute_bars(
        self,
        target: InstrumentTarget,
        trading_date: date,
        window: SessionWindow,
        now: datetime,
    ) -> MinuteBarBundle: ...

    async def close(self) -> None: ...


class MinuteBarStore(Protocol):
    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None: ...

    async def save_minute_bundle(self, bundle: MinuteBarBundle) -> None: ...

    async def confirm_minute_bar(self, bar: MinuteBar, confirmed_at: datetime) -> bool: ...

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]: ...

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MinuteBarCollection:
    trading_date: date
    collected: int
    confirmed: int
    pending: int


@dataclass(frozen=True, slots=True)
class MinuteBarCollector:
    calendar: MinuteBarCalendar
    source: MinuteBarSource
    store: MinuteBarStore

    async def collect(self, target: InstrumentTarget, now: datetime) -> MinuteBarCollection:
        try:
            trading_date, window = await self._resolve_session(now)
        except MinuteBarCollectionError as error:
            await self.store.mark_failed(target, now, error.failure.value, str(error))
            raise
        await self.store.mark_started(target, now)
        try:
            previous = {
                item.bar.bar_started_at: item
                for item in await self.store.minute_bars(target.symbol, trading_date)
            }
            bundle = await self.source.fetch_minute_bars(target, trading_date, window, now)
            bars = _collected_bars(bundle)
            await self.store.save_minute_bundle(bundle)
        except Exception as error:
            code = (
                error.failure.value
                if isinstance(error, MinuteBarCollectionError)
                else type(error).__name__
            )
            await self.store.mark_failed(target, now, code, str(error)[:500])
            raise
        confirmed = 0
        pending = 0
        for bar in bars:
            prior = previous.get(bar.bar_started_at)
            if prior is not None and prior.finality is BarFinality.CONFIRMED:
                confirmed += 1
                continue
            if (
                prior is not None
                and _is_final_evidence(prior, bar, now)
                and await self.store.confirm_minute_bar(bar, now)
            ):
                confirmed += 1
            else:
                pending += 1
        return MinuteBarCollection(
            trading_date=trading_date,
            collected=len(bars),
            confirmed=confirmed,
            pending=pending,
        )

    async def _resolve_session(self, now: datetime) -> tuple[date, SessionWindow]:
        today = now.astimezone(_SEOUL).date()
        record = await self._verified_session(today)
        window = calendar_session_window(record.session)
        if (
            window is not None
            and calendar_session_status(record.session) is not MarketSessionStatus.CLOSED
            and now >= window.opens_at + _MINUTE
        ):
            return today, window
        previous_date = await self.calendar.previous_open_date(_session_key(today))
        if previous_date is None:
            raise MinuteBarCollectionError(MinuteBarCollectionFailure.CALENDAR_COVERAGE)
        previous_record = await self._verified_session(previous_date)
        previous_window = calendar_session_window(previous_record.session)
        if previous_window is None:
            raise MinuteBarCollectionError(MinuteBarCollectionFailure.CALENDAR_COVERAGE)
        return previous_date, previous_window

    async def _verified_session(self, trading_date: date) -> MarketCalendarRecord:
        record = await self.calendar.session(_session_key(trading_date))
        if record is None:
            raise MinuteBarCollectionError(MinuteBarCollectionFailure.CALENDAR_COVERAGE)
        if calendar_verification_state(record.verification) is CalendarVerificationState.CONFLICT:
            raise MinuteBarCollectionError(MinuteBarCollectionFailure.CALENDAR_CONFLICT)
        return record


def _collected_bars(bundle: MinuteBarBundle) -> tuple[MinuteBar, ...]:
    bars = bundle.bars
    if not bars:
        raise MinuteBarCollectionError(MinuteBarCollectionFailure.EMPTY_COLLECTION)
    return bars


def _session_key(trading_date: date) -> CalendarSessionKey:
    return CalendarSessionKey(_COUNTRY, _EXCHANGE, trading_date, MarketSessionType.REGULAR)


def _is_final_evidence(prior: VersionedMinuteBar, bar: MinuteBar, now: datetime) -> bool:
    interval_end = bar.bar_started_at + _MINUTE
    return (
        now >= interval_end
        and prior.bar.received_at >= interval_end
        and prior.bar == replace(bar, received_at=prior.bar.received_at)
    )
