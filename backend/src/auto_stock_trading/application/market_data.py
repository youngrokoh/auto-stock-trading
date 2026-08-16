from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.adapters.brokers.kis_market_data import MarketDataSource
    from auto_stock_trading.domain.market_data.models import (
        DailyBar,
        Instrument,
        InstrumentTarget,
        MarketDataBundle,
        Quote,
        VersionedDailyBar,
    )


class MarketDataReader(Protocol):
    async def instrument(self, symbol: str) -> Instrument | None: ...

    async def quote(self, symbol: str) -> Quote | None: ...

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]: ...

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
