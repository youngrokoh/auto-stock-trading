from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from auto_stock_trading.domain.fundamentals.financial_statements import (
    FsDivision,
    ReportCode,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialReportObservation,
        FinancialStatementLine,
        VersionedFinancialReport,
    )
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

_INTERIM_CODES = (ReportCode.FIRST_QUARTER, ReportCode.HALF_YEAR, ReportCode.THIRD_QUARTER)

# 논리 보고서 하나를 가리키는 키. 사업연도 × 보고서 유형 × 연결구분이다.
type ReportKey = tuple[int, str, str]

NO_SKIP: Final[frozenset[ReportKey]] = frozenset()


class SourceQuotaExceededError(Exception):
    """출처의 요청 한도가 끝났다. 종목 실패와 달리 남은 종목도 모두 실패하므로 중단 사유다."""


class FinancialStatementSource(Protocol):
    @property
    def symbol(self) -> str: ...

    async def fetch_report(
        self,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> FinancialReportObservation: ...

    async def close(self) -> None: ...


class FinancialReportStore(Protocol):
    async def save_observation(self, observation: FinancialReportObservation) -> bool: ...

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None: ...

    async def mark_succeeded(self, target: InstrumentTarget, completed_at: datetime) -> None: ...

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def close(self) -> None: ...


class FinancialReportReader(Protocol):
    async def read_current_reports(self, symbol: str) -> tuple[VersionedFinancialReport, ...]: ...

    async def read_report(self, report_id: UUID) -> VersionedFinancialReport | None: ...

    async def read_report_lines(self, report_id: UUID) -> tuple[FinancialStatementLine, ...]: ...

    async def read_report_history(
        self,
        symbol: str,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> tuple[VersionedFinancialReport, ...]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ReportPeriod:
    bsns_year: int
    reprt_code: ReportCode


@dataclass(frozen=True, slots=True)
class FinancialCollection:
    saved: int
    skipped: int
    # 이어받기에서 현재 버전이 이미 있어 요청하지 않은 조합 수.
    existing: int = 0


def collection_plan(
    today: date,
    annual_years: int = 5,
    *,
    include_interim: bool = True,
) -> tuple[ReportPeriod, ...]:
    """수집할 보고서 기간. 연간 소급 깊이는 파라미터다(계약 §범위).

    시점 정합 학습은 과거 시점의 최신 사업보고서를 요구하므로 5개년으로는 부족할 수 있다.
    연간만 소급할 때는 분·반기를 건너뛴다 — 요청 수가 3배가 되고 쓰지 않는 기간이다.
    """
    latest_annual_year = today.year - 1
    annual = tuple(
        ReportPeriod(year, ReportCode.ANNUAL)
        for year in range(latest_annual_year - annual_years + 1, latest_annual_year + 1)
    )
    if not include_interim:
        return annual
    interim = tuple(ReportPeriod(today.year, code) for code in _INTERIM_CODES)
    return annual + interim


@dataclass(frozen=True, slots=True)
class FinancialStatementCollector:
    source: FinancialStatementSource
    store: FinancialReportStore

    async def collect(
        self,
        target: InstrumentTarget,
        periods: tuple[ReportPeriod, ...],
        now: datetime,
        skip: frozenset[ReportKey] = NO_SKIP,
    ) -> FinancialCollection:
        """`skip`은 이어받기 전용이다. 비우면 전량 재조회로 정정 공시를 반영한다."""
        await self.store.mark_started(target, now)
        saved = 0
        skipped = 0
        existing = 0
        try:
            for period in periods:
                for fs_div in (FsDivision.CONSOLIDATED, FsDivision.SEPARATE):
                    if (period.bsns_year, period.reprt_code.value, fs_div.value) in skip:
                        existing += 1
                        continue
                    observation = await self.source.fetch_report(
                        period.bsns_year,
                        period.reprt_code,
                        fs_div,
                    )
                    if await self.store.save_observation(observation):
                        saved += 1
                    else:
                        skipped += 1
        except Exception as error:
            await self.store.mark_failed(target, now, type(error).__name__, str(error)[:500])
            raise
        await self.store.mark_succeeded(target, now)
        return FinancialCollection(saved=saved, skipped=skipped, existing=existing)
