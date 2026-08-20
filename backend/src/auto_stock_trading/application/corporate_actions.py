from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import anyio

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.market_data.corp_codes import DartCorpCode
    from auto_stock_trading.domain.market_data.corporate_actions import CorporateActionBundle

# 종목당 상한. 응답이 매달리면 한 종목이 전체 수집을 멈춘다(시세 스윕 실측).
_SYMBOL_TIMEOUT_SECONDS: Final = 120.0


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


class UniverseCorpCodes(Protocol):
    async def universe_symbols(self) -> tuple[str, ...]: ...

    async def universe_corp_codes(self) -> tuple[DartCorpCode, ...]: ...


class UniverseDividendSource(Protocol):
    async def collect_symbol(
        self,
        symbol: str,
        corp_code: str,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class UniverseDividendResult:
    symbols: int
    observations: int
    failed: int
    missing_corp_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniverseDividendCollection:
    """유니버스 전 종목 배당 수집. 고유번호가 없는 종목은 조회 방법이 없으므로 보고한다."""

    codes: UniverseCorpCodes
    source: UniverseDividendSource
    symbol_timeout_seconds: float = _SYMBOL_TIMEOUT_SECONDS

    async def run(
        self,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> UniverseDividendResult:
        universe = await self.codes.universe_symbols()
        known = await self.codes.universe_corp_codes()
        mapped = {item.symbol: item.corp_code for item in known}
        observations = 0
        failed = 0
        for item in known:
            try:
                with anyio.fail_after(self.symbol_timeout_seconds):
                    observations += await self.source.collect_symbol(
                        item.symbol,
                        item.corp_code,
                        start_date,
                        end_date,
                        now,
                    )
            except Exception:  # noqa: BLE001 — 종목 실패는 수집을 멈추지 않는다
                failed += 1
        return UniverseDividendResult(
            symbols=len(known),
            observations=observations,
            failed=failed,
            missing_corp_codes=tuple(symbol for symbol in universe if symbol not in mapped),
        )
