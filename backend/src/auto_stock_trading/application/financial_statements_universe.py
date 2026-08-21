"""유니버스 전 종목 재무제표 수집 스윕(재무제표 계약 §유니버스 수집 규칙).

종목당 수집 규칙 자체는 `FinancialStatementCollector`가 그대로 갖는다. 이 모듈은 대상
선정과 실패 처리만 맡는다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import anyio

from auto_stock_trading.application.financial_statements import SourceQuotaExceededError

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.application.financial_statements import (
        FinancialCollection,
        ReportKey,
        ReportPeriod,
    )
    from auto_stock_trading.domain.fundamentals.financial_statements import (
        VersionedFinancialReport,
    )
    from auto_stock_trading.domain.market_data.corp_codes import DartCorpCode

_SWEEP_KEY: Final = "KOSPI200"
_PARTIAL_FAILURE: Final = "partial_failure"
_QUOTA_EXCEEDED: Final = "quota_exceeded"
# 종목당 상한. 응답이 매달리면 한 종목이 전체 스윕을 멈춘다(시세 스윕 실측).
_SYMBOL_TIMEOUT_SECONDS: Final = 180.0


class UniverseCorpCodes(Protocol):
    async def universe_symbols(self) -> tuple[str, ...]: ...

    async def universe_corp_codes(self) -> tuple[DartCorpCode, ...]: ...


class SymbolStatementCollector(Protocol):
    """종목 하나의 재무제표 수집 한 단위."""

    async def collect_symbol(
        self,
        symbol: str,
        corp_code: str,
        periods: tuple[ReportPeriod, ...],
        now: datetime,
        skip: frozenset[ReportKey],
    ) -> FinancialCollection: ...


class CurrentReports(Protocol):
    async def read_current_reports(self, symbol: str) -> tuple[VersionedFinancialReport, ...]: ...


class SweepStatus(Protocol):
    async def mark_sweep_started(self, key: str, started_at: datetime) -> None: ...

    async def mark_sweep_succeeded(self, key: str, completed_at: datetime) -> None: ...

    async def mark_sweep_failed(
        self,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class UniverseStatementResult:
    symbols: int
    saved: int
    skipped: int
    existing: int
    # 실패한 종목을 이름으로 남긴다. 개수만 세면 운영자가 무엇을 다시 돌릴지 알 수 없다.
    failed_symbols: tuple[str, ...]
    missing_corp_codes: tuple[str, ...]
    remaining_symbols: tuple[str, ...]
    quota_exhausted: bool


@dataclass(frozen=True, slots=True)
class UniverseStatementCollection:
    codes: UniverseCorpCodes
    source: SymbolStatementCollector
    reports: CurrentReports
    status: SweepStatus
    # 기본값은 전량 재조회다. 생략하면 정정 공시를 영구히 놓친다(계약 §유니버스 3).
    only_missing: bool = False
    symbol_timeout_seconds: float = _SYMBOL_TIMEOUT_SECONDS

    async def run(
        self,
        periods: tuple[ReportPeriod, ...],
        now: datetime,
    ) -> UniverseStatementResult:
        universe = await self.codes.universe_symbols()
        known = await self.codes.universe_corp_codes()
        mapped = {item.symbol for item in known}
        await self.status.mark_sweep_started(_SWEEP_KEY, now)
        saved = 0
        skipped = 0
        existing = 0
        failures: list[str] = []
        remaining: tuple[str, ...] = ()
        for index, item in enumerate(known):
            try:
                with anyio.fail_after(self.symbol_timeout_seconds):
                    result = await self.source.collect_symbol(
                        item.symbol,
                        item.corp_code,
                        periods,
                        now,
                        await self._skip_keys(item.symbol),
                    )
            except SourceQuotaExceededError:
                # 한도가 끝났으면 남은 종목도 모두 실패한다. 계속 두드리지 않는다.
                remaining = tuple(entry.symbol for entry in known[index:])
                break
            except Exception:  # noqa: BLE001 — 종목 실패는 스윕을 멈추지 않는다
                failures.append(item.symbol)
            else:
                saved += result.saved
                skipped += result.skipped
                existing += result.existing
        await self._record(now, failures, remaining)
        return UniverseStatementResult(
            symbols=len(known),
            saved=saved,
            skipped=skipped,
            existing=existing,
            failed_symbols=tuple(failures),
            missing_corp_codes=tuple(symbol for symbol in universe if symbol not in mapped),
            remaining_symbols=remaining,
            quota_exhausted=bool(remaining),
        )

    async def _skip_keys(self, symbol: str) -> frozenset[ReportKey]:
        if not self.only_missing:
            return frozenset()
        return frozenset(
            (report.bsns_year, report.reprt_code.value, report.fs_div.value)
            for report in await self.reports.read_current_reports(symbol)
        )

    async def _record(
        self,
        now: datetime,
        failures: list[str],
        remaining: tuple[str, ...],
    ) -> None:
        if remaining:
            await self.status.mark_sweep_failed(
                _SWEEP_KEY,
                now,
                _QUOTA_EXCEEDED,
                f"request quota exhausted with {len(remaining)} symbols left",
            )
        elif failures:
            await self.status.mark_sweep_failed(
                _SWEEP_KEY,
                now,
                _PARTIAL_FAILURE,
                f"{len(failures)} universe financial statement symbols failed",
            )
        else:
            await self.status.mark_sweep_succeeded(_SWEEP_KEY, now)
