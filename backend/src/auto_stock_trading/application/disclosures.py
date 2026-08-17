from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.fundamentals.disclosures import (
        Disclosure,
        DisclosureBundle,
    )
    from auto_stock_trading.domain.market_data.models import InstrumentTarget


class DisclosureSource(Protocol):
    @property
    def symbol(self) -> str: ...

    async def fetch_disclosures(
        self,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> DisclosureBundle: ...

    async def close(self) -> None: ...


class DisclosureStore(Protocol):
    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None: ...

    async def save_disclosure_bundle(self, bundle: DisclosureBundle) -> int: ...

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def close(self) -> None: ...


class DisclosureReader(Protocol):
    async def read_disclosures(self, symbol: str, limit: int) -> tuple[Disclosure, ...]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DisclosureCollection:
    saved: int
    observed: int


@dataclass(frozen=True, slots=True)
class DisclosureCollector:
    source: DisclosureSource
    store: DisclosureStore

    async def collect(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> DisclosureCollection:
        await self.store.mark_started(target, now)
        try:
            bundle = await self.source.fetch_disclosures(start_date, end_date, now)
            saved = await self.store.save_disclosure_bundle(bundle)
        except Exception as error:
            await self.store.mark_failed(target, now, type(error).__name__, str(error)[:500])
            raise
        return DisclosureCollection(saved=saved, observed=len(bundle.disclosures))
