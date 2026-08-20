"""종목 유니버스 수집과 시세 스윕(종목 유니버스 계약).

일봉 이력 백필은 이 슬라이스 범위가 아니다. 스윕은 현재가 단건 조회만 쓴다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import anyio

from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.models import QuoteSnapshotObservation
    from auto_stock_trading.domain.market_data.stocks import StockMasterBundle

_MASTER_OPERATION: Final = "stock_master"
_QUOTE_OPERATION: Final = "universe_quote"
_SWEEP_KEY: Final = "KOSPI200"
_PARTIAL_FAILURE: Final = "partial_failure"
_SYMBOL_TIMEOUT_SECONDS: Final = 60.0


class StockMasterSource(Protocol):
    async def fetch_master(self, now: datetime) -> StockMasterBundle: ...

    async def close(self) -> None: ...


class UniverseQuoteSource(Protocol):
    async def fetch_quote_snapshot(
        self,
        target: InstrumentTarget,
    ) -> QuoteSnapshotObservation: ...

    async def close(self) -> None: ...


class StockUniverseStore(Protocol):
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

    async def save_master_bundle(self, bundle: StockMasterBundle) -> int: ...

    async def save_quote_snapshot(self, observation: QuoteSnapshotObservation) -> None: ...

    async def universe_symbols(self) -> tuple[str, ...]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UniverseCollection:
    observed: int
    saved: int


@dataclass(frozen=True, slots=True)
class StockUniverseCollector:
    source: StockMasterSource
    store: StockUniverseStore

    async def collect(self, now: datetime) -> UniverseCollection:
        await self.store.mark_started(_MASTER_OPERATION, _SWEEP_KEY, now)
        try:
            bundle = await self.source.fetch_master(now)
            saved = await self.store.save_master_bundle(bundle)
        except Exception as error:
            await self.store.mark_failed(
                _MASTER_OPERATION,
                _SWEEP_KEY,
                now,
                type(error).__name__,
                str(error)[:500],
            )
            raise
        await self.store.mark_succeeded(_MASTER_OPERATION, _SWEEP_KEY, now)
        return UniverseCollection(observed=len(bundle.profiles), saved=saved)


@dataclass(frozen=True, slots=True)
class QuoteSweepResult:
    collected: int
    failed: int


@dataclass(frozen=True, slots=True)
class QuoteSweeper:
    source: UniverseQuoteSource
    store: StockUniverseStore
    # 종목당 상한. HTTP 읽기 타임아웃이 걸리지 않고 응답이 매달리는 경우를 실측했다.
    symbol_timeout_seconds: float = _SYMBOL_TIMEOUT_SECONDS

    async def collect(self, now: datetime) -> QuoteSweepResult:
        """개별 종목 실패는 기록하고 계속한다. 요청 간격은 어댑터가 직렬화한다."""
        await self.store.mark_started(_QUOTE_OPERATION, _SWEEP_KEY, now)
        collected = 0
        failed = 0
        for symbol in await self.store.universe_symbols():
            try:
                with anyio.fail_after(self.symbol_timeout_seconds):
                    observation = await self.source.fetch_quote_snapshot(
                        InstrumentTarget(symbol, ProductType.STOCK)
                    )
                    await self.store.save_quote_snapshot(observation)
            except Exception:  # noqa: BLE001 — 개별 종목 실패는 스윕을 멈추지 않는다
                failed += 1
            else:
                collected += 1
        if failed > 0:
            await self.store.mark_failed(
                _QUOTE_OPERATION,
                _SWEEP_KEY,
                now,
                _PARTIAL_FAILURE,
                f"{failed} of {collected + failed} universe quotes failed",
            )
        else:
            await self.store.mark_succeeded(_QUOTE_OPERATION, _SWEEP_KEY, now)
        return QuoteSweepResult(collected=collected, failed=failed)
