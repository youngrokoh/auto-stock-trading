from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import TYPE_CHECKING, Final, Protocol
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.market_data.models import BarFinality

if TYPE_CHECKING:
    from datetime import date

    from auto_stock_trading.adapters.brokers.kis_market_data import MarketDataSource
    from auto_stock_trading.domain.market_data.minute_bars import VersionedMinuteBar
    from auto_stock_trading.domain.market_data.models import (
        DailyBar,
        Instrument,
        InstrumentTarget,
        MarketDataBundle,
        Quote,
        VersionedDailyBar,
    )

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_DAILY_BAR_FINALITY_CUTOFF: Final = time(15, 40)


class MarketDataReader(Protocol):
    async def instrument(self, symbol: str) -> Instrument | None: ...

    async def quote(self, symbol: str) -> Quote | None: ...

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]: ...

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]: ...

    async def close(self) -> None: ...


class MarketDataStore(MarketDataReader, Protocol):
    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None: ...

    async def save_bundle(self, bundle: MarketDataBundle) -> None: ...

    async def confirm_daily_bar(self, bar: DailyBar, confirmed_at: datetime) -> bool: ...

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DailyBarConfirmation:
    confirmed: int
    pending: int


@dataclass(frozen=True, slots=True)
class DailyBarConfirmer:
    source: MarketDataSource
    store: MarketDataStore

    async def confirm(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> DailyBarConfirmation:
        previous_bars = {
            item.bar.trading_date: item
            for item in await self.store.daily_bars(target.symbol, start_date, end_date)
        }
        bundle = await self.source.fetch_bundle(target, start_date, end_date)
        await self.store.save_bundle(bundle)
        confirmed = 0
        pending = 0
        for bar in bundle.daily_bars:
            previous = previous_bars.get(bar.trading_date)
            if previous is not None and previous.finality is BarFinality.CONFIRMED:
                confirmed += 1
                continue
            if (
                previous is not None
                and _is_final_evidence(previous, bar, now)
                and await self.store.confirm_daily_bar(bar, now)
            ):
                confirmed += 1
            else:
                pending += 1
        return DailyBarConfirmation(confirmed=confirmed, pending=pending)


def _is_final_evidence(previous: VersionedDailyBar, bar: DailyBar, now: datetime) -> bool:
    cutoff = datetime.combine(bar.trading_date, _DAILY_BAR_FINALITY_CUTOFF, _SEOUL)
    return (
        now.astimezone(_SEOUL) > cutoff
        and previous.bar.received_at.astimezone(_SEOUL) > cutoff
        and previous.bar == replace(bar, received_at=previous.bar.received_at)
    )


@dataclass(frozen=True, slots=True)
class MarketDataCollector:
    source: MarketDataSource
    store: MarketDataStore

    async def collect(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        started_at: datetime,
    ) -> MarketDataBundle:
        await self.store.mark_started(target, started_at)
        try:
            bundle = await self.source.fetch_bundle(target, start_date, end_date)
            await self.store.save_bundle(bundle)
        except Exception as error:
            await self.store.mark_failed(
                target,
                started_at,
                type(error).__name__,
                str(error)[:500],
            )
            raise
        return bundle
