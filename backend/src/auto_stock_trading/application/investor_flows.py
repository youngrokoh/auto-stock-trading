from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, override

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.investor_flows import (
        InvestorFlowBundle,
        VersionedInvestorFlow,
    )
    from auto_stock_trading.domain.market_data.models import InstrumentTarget


class InvestorFlowCollectionFailure(StrEnum):
    EMPTY_COLLECTION = "investor_flows_missing"


@dataclass(frozen=True, slots=True)
class InvestorFlowCollectionError(Exception):
    failure: InvestorFlowCollectionFailure

    @override
    def __str__(self) -> str:
        return self.failure.value


class InvestorFlowSource(Protocol):
    async def fetch_flows(self, target: InstrumentTarget, now: datetime) -> InvestorFlowBundle: ...

    async def close(self) -> None: ...


class InvestorFlowStore(Protocol):
    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None: ...

    async def save_flow_bundle(self, bundle: InvestorFlowBundle) -> None: ...

    async def investor_flows(
        self,
        symbol: str,
        limit: int,
    ) -> tuple[VersionedInvestorFlow, ...]: ...

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InvestorFlowCollection:
    collected: int


@dataclass(frozen=True, slots=True)
class InvestorFlowCollector:
    source: InvestorFlowSource
    store: InvestorFlowStore

    async def collect(self, target: InstrumentTarget, now: datetime) -> InvestorFlowCollection:
        await self.store.mark_started(target, now)
        try:
            bundle = await self.source.fetch_flows(target, now)
            if not bundle.flows:
                raise InvestorFlowCollectionError(  # noqa: TRY301
                    InvestorFlowCollectionFailure.EMPTY_COLLECTION
                )
            await self.store.save_flow_bundle(bundle)
        except Exception as error:
            code = (
                error.failure.value
                if isinstance(error, InvestorFlowCollectionError)
                else type(error).__name__
            )
            await self.store.mark_failed(target, now, code, str(error)[:500])
            raise
        return InvestorFlowCollection(collected=len(bundle.flows))
