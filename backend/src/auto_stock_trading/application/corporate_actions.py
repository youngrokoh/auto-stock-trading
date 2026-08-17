from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.market_data.corporate_actions import CorporateActionBundle


class CorporateActionSource(Protocol):
    @property
    def source_name(self) -> str: ...

    @property
    def symbol(self) -> str: ...

    async def fetch_corporate_actions(
        self,
        start_date: date,
        end_date: date,
    ) -> CorporateActionBundle: ...

    async def close(self) -> None: ...


class CorporateActionStore(Protocol):
    async def save_bundle(self, bundle: CorporateActionBundle) -> None: ...

    async def mark_sync_started(self, source: str, symbol: str, started_at: datetime) -> None: ...

    async def mark_sync_succeeded(
        self,
        source: str,
        symbol: str,
        completed_at: datetime,
    ) -> None: ...

    async def mark_sync_failed(
        self,
        source: str,
        symbol: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CorporateActionCollector:
    source: CorporateActionSource
    store: CorporateActionStore

    async def collect(
        self,
        start_date: date,
        end_date: date,
        started_at: datetime,
    ) -> CorporateActionBundle:
        source_name = self.source.source_name
        symbol = self.source.symbol
        await self.store.mark_sync_started(source_name, symbol, started_at)
        try:
            bundle = await self.source.fetch_corporate_actions(start_date, end_date)
            await self.store.save_bundle(bundle)
        except Exception as error:
            await self.store.mark_sync_failed(
                source_name,
                symbol,
                started_at,
                type(error).__name__,
                str(error)[:500],
            )
            raise
        await self.store.mark_sync_succeeded(source_name, symbol, bundle.collected_at)
        return bundle
