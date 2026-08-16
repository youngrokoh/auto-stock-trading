from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Protocol, final, override
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.market_data.calendar import (
    CalendarObservation,
    CalendarSessionKey,
    CalendarSessionRange,
    MarketCalendarRecord,
    calendar_session_key,
)

if TYPE_CHECKING:
    from datetime import datetime

_SEOUL = ZoneInfo("Asia/Seoul")


class MarketCalendarSource(Protocol):
    async def fetch_sessions(
        self,
        query: CalendarSessionRange,
    ) -> tuple[CalendarObservation, ...]: ...

    async def close(self) -> None: ...


class MarketCalendarVerifier(Protocol):
    async def verify(self, current: MarketCalendarRecord) -> CalendarObservation: ...

    async def close(self) -> None: ...


class MarketCalendarStore(Protocol):
    async def save_all(
        self,
        observations: tuple[CalendarObservation, ...],
    ) -> tuple[MarketCalendarRecord, ...]: ...

    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None: ...

    async def mark_sync_started(
        self,
        source: str,
        target: str,
        started_at: datetime,
    ) -> None: ...

    async def mark_sync_succeeded(
        self,
        source: str,
        target: str,
        completed_at: datetime,
    ) -> None: ...

    async def mark_sync_failed(
        self,
        source: str,
        target: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def close(self) -> None: ...


@final
@dataclass(frozen=True, slots=True)
class IncompleteCalendarRangeError(Exception):
    @override
    def __str__(self) -> str:
        return "KRX market calendar response did not cover the requested range"


@final
@dataclass(frozen=True, slots=True)
class MissingPrimaryCalendarError(Exception):
    key: CalendarSessionKey

    @override
    def __str__(self) -> str:
        return f"KRX market calendar is missing for {self.key.exchange}:{self.key.trading_date}"


@final
@dataclass(frozen=True, slots=True)
class SameDayConfirmationRequiredError(Exception):
    key: CalendarSessionKey

    @override
    def __str__(self) -> str:
        return f"KIS confirmation must run on {self.key.exchange}:{self.key.trading_date}"


@dataclass(frozen=True, slots=True)
class KrxCalendarCollector:
    source: MarketCalendarSource
    store: MarketCalendarStore

    async def collect(
        self,
        query: CalendarSessionRange,
        started_at: datetime,
    ) -> tuple[MarketCalendarRecord, ...]:
        target = f"{query.exchange}:{query.start_date.year}-{query.end_date.year}"
        await self.store.mark_sync_started("KRX", target, started_at)
        try:
            observations = await self.source.fetch_sessions(query)
            _require_complete_range(query, observations)
            records = await self.store.save_all(observations)
        except Exception as error:
            await self.store.mark_sync_failed(
                "KRX",
                target,
                started_at,
                type(error).__name__,
                str(error)[:500],
            )
            raise
        completed_at = max(item.raw_response.received_at for item in observations)
        await self.store.mark_sync_succeeded("KRX", target, completed_at)
        return records


@dataclass(frozen=True, slots=True)
class KisCalendarConfirmer:
    verifier: MarketCalendarVerifier
    store: MarketCalendarStore

    async def confirm(
        self,
        key: CalendarSessionKey,
        started_at: datetime,
    ) -> MarketCalendarRecord:
        target = f"{key.exchange}:{key.trading_date}"
        await self.store.mark_sync_started("KIS", target, started_at)
        try:
            _require_same_day(key, started_at)
            current = _require_current(key, await self.store.session(key))
            observation = await self.verifier.verify(current)
            records = await self.store.save_all((observation,))
        except Exception as error:
            await self.store.mark_sync_failed(
                "KIS",
                target,
                started_at,
                type(error).__name__,
                str(error)[:500],
            )
            raise
        await self.store.mark_sync_succeeded("KIS", target, observation.raw_response.received_at)
        return records[0]


def _require_complete_range(
    query: CalendarSessionRange,
    observations: tuple[CalendarObservation, ...],
) -> None:
    expected_dates = tuple(
        date.fromordinal(ordinal)
        for ordinal in range(query.start_date.toordinal(), query.end_date.toordinal() + 1)
    )
    actual_dates = tuple(calendar_session_key(item.session).trading_date for item in observations)
    if actual_dates != expected_dates:
        raise IncompleteCalendarRangeError


def _require_same_day(key: CalendarSessionKey, started_at: datetime) -> None:
    if started_at.astimezone(_SEOUL).date() != key.trading_date:
        raise SameDayConfirmationRequiredError(key)


def _require_current(
    key: CalendarSessionKey,
    current: MarketCalendarRecord | None,
) -> MarketCalendarRecord:
    if current is None:
        raise MissingPrimaryCalendarError(key)
    return current
