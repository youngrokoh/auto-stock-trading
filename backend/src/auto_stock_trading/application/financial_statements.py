from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

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


def collection_plan(today: date, annual_years: int = 5) -> tuple[ReportPeriod, ...]:
    latest_annual_year = today.year - 1
    annual = tuple(
        ReportPeriod(year, ReportCode.ANNUAL)
        for year in range(latest_annual_year - annual_years + 1, latest_annual_year + 1)
    )
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
    ) -> FinancialCollection:
        await self.store.mark_started(target, now)
        saved = 0
        skipped = 0
        try:
            for period in periods:
                for fs_div in (FsDivision.CONSOLIDATED, FsDivision.SEPARATE):
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
        return FinancialCollection(saved=saved, skipped=skipped)
