"""종목 유니버스 수집과 시세 스윕(종목 유니버스 계약).

일봉 이력 백필은 이 슬라이스 범위가 아니다. 스윕은 현재가 단건 조회만 쓴다.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol

import anyio

from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.application.market_data import DailyBarConfirmation
    from auto_stock_trading.domain.market_data.models import QuoteSnapshotObservation
    from auto_stock_trading.domain.market_data.stocks import StockMasterBundle

_MASTER_OPERATION: Final = "stock_master"
_CHUNK_DAYS: Final = 120
_CHUNK_TIMEOUT_SECONDS: Final = 120.0
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


class UniverseSymbols(Protocol):
    async def universe_symbols(self) -> tuple[str, ...]: ...


class BarCollector(Protocol):
    """일봉 수집 한 단위. `MarketDataCollector`가 그대로 만족한다."""

    async def collect(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        started_at: datetime,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class BackfillResult:
    symbols: int
    collected_chunks: int
    failed_chunks: int


def _chunks(start_date: date, end_date: date, chunk_days: int) -> tuple[tuple[date, date], ...]:
    """회당 최대 100봉 제한 때문에 창을 나눈다. 구간은 겹치지 않고 하루도 비지 않는다."""
    windows: list[tuple[date, date]] = []
    cursor = start_date
    step = timedelta(days=chunk_days - 1)
    while cursor <= end_date:
        stop = min(cursor + step, end_date)
        windows.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return tuple(windows)


@dataclass(frozen=True, slots=True)
class UniverseBarBackfill:
    """유니버스 전 종목 일봉 백필. 종목·구간 하나가 전체를 멈추지 못하게 한다."""

    universe: UniverseSymbols
    collector: BarCollector
    chunk_days: int = _CHUNK_DAYS
    chunk_timeout_seconds: float = _CHUNK_TIMEOUT_SECONDS

    async def run(self, start_date: date, end_date: date, now: datetime) -> BackfillResult:
        symbols = await self.universe.universe_symbols()
        windows = _chunks(start_date, end_date, self.chunk_days)
        collected = 0
        failed = 0
        for symbol in symbols:
            target = InstrumentTarget(symbol, ProductType.STOCK)
            for window_start, window_end in windows:
                try:
                    with anyio.fail_after(self.chunk_timeout_seconds):
                        _ = await self.collector.collect(target, window_start, window_end, now)
                except Exception:  # noqa: BLE001 — 구간 실패는 백필을 멈추지 않는다
                    failed += 1
                else:
                    collected += 1
        return BackfillResult(
            symbols=len(symbols),
            collected_chunks=collected,
            failed_chunks=failed,
        )


class BarConfirmer(Protocol):
    """일봉 확정 한 단위. `DailyBarConfirmer`가 그대로 만족한다."""

    async def confirm(
        self,
        target: InstrumentTarget,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> DailyBarConfirmation: ...


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    symbols: int
    confirmed: int
    pending: int
    failed_chunks: int


@dataclass(frozen=True, slots=True)
class UniverseBarConfirmation:
    """유니버스 전 종목 일봉 확정 패스. 확정 규칙 자체는 `DailyBarConfirmer`가 갖는다."""

    universe: UniverseSymbols
    confirmer: BarConfirmer
    chunk_days: int = _CHUNK_DAYS
    chunk_timeout_seconds: float = _CHUNK_TIMEOUT_SECONDS

    async def run(self, start_date: date, end_date: date, now: datetime) -> ConfirmationResult:
        symbols = await self.universe.universe_symbols()
        windows = _chunks(start_date, end_date, self.chunk_days)
        confirmed = 0
        pending = 0
        failed = 0
        for symbol in symbols:
            target = InstrumentTarget(symbol, ProductType.STOCK)
            for window_start, window_end in windows:
                try:
                    with anyio.fail_after(self.chunk_timeout_seconds):
                        result = await self.confirmer.confirm(target, window_start, window_end, now)
                except Exception:  # noqa: BLE001 — 구간 실패는 확정 패스를 멈추지 않는다
                    failed += 1
                else:
                    confirmed += result.confirmed
                    pending += result.pending
        return ConfirmationResult(
            symbols=len(symbols),
            confirmed=confirmed,
            pending=pending,
            failed_chunks=failed,
        )
