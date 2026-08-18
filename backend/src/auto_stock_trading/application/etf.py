from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionLifecycle,
    CorporateActionType,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.market_data.corporate_actions import (
        VersionedCorporateAction,
    )
    from auto_stock_trading.domain.market_data.etf import (
        EtfListing,
        EtfMasterBundle,
        EtfNavObservation,
        EtfNavSnapshot,
        VersionedEtfProfile,
    )

_MASTER_OPERATION = "etf_master"
_NAV_OPERATION = "etf_nav"
_SWEEP_KEY = "ETF"
_YIELD_QUANTUM = Decimal("0.01")
_HUNDRED = Decimal(100)
_YIELD_WINDOW = timedelta(days=365)


class EtfMasterSource(Protocol):
    async def fetch_master(self, now: datetime) -> EtfMasterBundle: ...

    async def close(self) -> None: ...


class EtfNavSource(Protocol):
    async def fetch_snapshot(self, symbol: str) -> EtfNavObservation: ...

    async def close(self) -> None: ...


class EtfStore(Protocol):
    async def mark_started(self, operation: str, key: str, started_at: datetime) -> None: ...

    async def mark_succeeded(self, operation: str, key: str, completed_at: datetime) -> None: ...

    async def mark_failed(
        self,
        operation: str,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def save_master_bundle(self, bundle: EtfMasterBundle) -> int: ...

    async def save_nav_observation(self, observation: EtfNavObservation) -> None: ...

    async def profiles(self) -> tuple[VersionedEtfProfile, ...]: ...

    async def close(self) -> None: ...


class EtfReader(Protocol):
    async def read_etf_list(self) -> tuple[EtfListing, ...]: ...

    async def read_etf(self, symbol: str) -> EtfListing | None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class EtfMasterCollection:
    observed: int
    saved: int


@dataclass(frozen=True, slots=True)
class EtfMasterCollector:
    source: EtfMasterSource
    store: EtfStore

    async def collect(self, now: datetime) -> EtfMasterCollection:
        await self.store.mark_started(_MASTER_OPERATION, _SWEEP_KEY, now)
        try:
            bundle = await self.source.fetch_master(now)
            saved = await self.store.save_master_bundle(bundle)
        except Exception as error:
            await self.store.mark_failed(
                _MASTER_OPERATION, _SWEEP_KEY, now, type(error).__name__, str(error)[:500]
            )
            raise
        await self.store.mark_succeeded(_MASTER_OPERATION, _SWEEP_KEY, now)
        return EtfMasterCollection(observed=len(bundle.profiles), saved=saved)


@dataclass(frozen=True, slots=True)
class EtfNavSweepResult:
    collected: int
    failed: int


@dataclass(frozen=True, slots=True)
class EtfNavSweeper:
    source: EtfNavSource
    store: EtfStore

    async def collect(self, now: datetime) -> EtfNavSweepResult:
        await self.store.mark_started(_NAV_OPERATION, _SWEEP_KEY, now)
        collected = 0
        failed = 0
        for profile in await self.store.profiles():
            try:
                observation = await self.source.fetch_snapshot(profile.symbol)
                await self.store.save_nav_observation(observation)
                collected += 1
            except Exception:  # noqa: BLE001 — 개별 종목 실패는 기록 후 계속한다
                failed += 1
        if failed > 0:
            await self.store.mark_failed(
                _NAV_OPERATION,
                _SWEEP_KEY,
                now,
                "partial_failure",
                f"{failed} of {collected + failed} ETF snapshots failed",
            )
        else:
            await self.store.mark_succeeded(_NAV_OPERATION, _SWEEP_KEY, now)
        return EtfNavSweepResult(collected=collected, failed=failed)


class DistributionYieldUnavailableReason(StrEnum):
    MISSING_SNAPSHOT = "MISSING_SNAPSHOT"
    MISSING_DISTRIBUTIONS = "MISSING_DISTRIBUTIONS"
    ZERO_PRICE = "ZERO_PRICE"


@dataclass(frozen=True, slots=True)
class DistributionYield:
    value: Decimal | None
    unavailable_reason: DistributionYieldUnavailableReason | None
    formula: str
    distribution_total: Decimal | None
    distribution_count: int
    window_start: date | None
    window_end: date | None


def distribution_yield(
    actions: tuple[VersionedCorporateAction, ...],
    snapshot: EtfNavSnapshot | None,
) -> DistributionYield:
    formula = "최근 12개월 주당 분배금 합계 ÷ 현재가 × 100"
    if snapshot is None:
        return _unavailable_yield(formula, DistributionYieldUnavailableReason.MISSING_SNAPSHOT)
    window_end = snapshot.as_of.date()
    window_start = (snapshot.as_of - _YIELD_WINDOW).date()
    amounts = [
        item.action.cash_amount
        for item in actions
        if item.action.action_type is CorporateActionType.ETF_DISTRIBUTION
        and item.action.lifecycle is not CorporateActionLifecycle.CANCELLED
        and item.action.cash_amount is not None
        and item.action.ex_date is not None
        and window_start < item.action.ex_date <= window_end
    ]
    if not amounts:
        return _unavailable_yield(formula, DistributionYieldUnavailableReason.MISSING_DISTRIBUTIONS)
    if snapshot.price == 0:
        return _unavailable_yield(formula, DistributionYieldUnavailableReason.ZERO_PRICE)
    total = sum(amounts, Decimal(0))
    return DistributionYield(
        value=(total / snapshot.price * _HUNDRED).quantize(_YIELD_QUANTUM, rounding=ROUND_HALF_UP),
        unavailable_reason=None,
        formula=formula,
        distribution_total=total,
        distribution_count=len(amounts),
        window_start=window_start,
        window_end=window_end,
    )


def _unavailable_yield(
    formula: str,
    reason: DistributionYieldUnavailableReason,
) -> DistributionYield:
    return DistributionYield(
        value=None,
        unavailable_reason=reason,
        formula=formula,
        distribution_total=None,
        distribution_count=0,
        window_start=None,
        window_end=None,
    )
