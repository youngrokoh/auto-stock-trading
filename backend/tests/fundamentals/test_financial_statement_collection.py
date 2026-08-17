from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import final
from uuid import uuid4

import anyio
import pytest

from auto_stock_trading.application.financial_statements import (
    FinancialStatementCollector,
    ReportPeriod,
    collection_plan,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialRawResponse,
    FinancialReport,
    FinancialReportObservation,
    FsDivision,
    ReportCode,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType

_TARGET = InstrumentTarget("005930", ProductType.STOCK)
_NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def test_collection_plan_covers_five_annual_years_and_current_interim_reports() -> None:
    plan = collection_plan(date(2026, 8, 17), annual_years=5)

    assert plan == (
        ReportPeriod(2021, ReportCode.ANNUAL),
        ReportPeriod(2022, ReportCode.ANNUAL),
        ReportPeriod(2023, ReportCode.ANNUAL),
        ReportPeriod(2024, ReportCode.ANNUAL),
        ReportPeriod(2025, ReportCode.ANNUAL),
        ReportPeriod(2026, ReportCode.FIRST_QUARTER),
        ReportPeriod(2026, ReportCode.HALF_YEAR),
        ReportPeriod(2026, ReportCode.THIRD_QUARTER),
    )


def _observation(
    bsns_year: int,
    reprt_code: ReportCode,
    fs_div: FsDivision,
    *,
    missing: bool,
) -> FinancialReportObservation:
    report = (
        None
        if missing
        else FinancialReport(
            symbol=_TARGET.symbol,
            corp_code="00126380",
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            rcept_no="20260310000001",
            currency="KRW",
            received_at=_NOW,
            lines=(),
        )
    )
    return FinancialReportObservation(
        raw=FinancialRawResponse(
            endpoint="/api/fnlttSinglAcntAll.json",
            request_fingerprint=f"test:{uuid4()}",
            received_at=_NOW,
            payload_json="{}",
        ),
        report=report,
    )


@final
@dataclass
class FakeSource:
    missing_periods: frozenset[tuple[int, ReportCode]] = frozenset()
    requests: list[tuple[int, ReportCode, FsDivision]] = field(default_factory=list)
    fail_on: tuple[int, ReportCode] | None = None

    @property
    def symbol(self) -> str:
        return _TARGET.symbol

    async def fetch_report(
        self,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> FinancialReportObservation:
        self.requests.append((bsns_year, reprt_code, fs_div))
        if self.fail_on == (bsns_year, reprt_code):
            message = "테스트 계약 위반"
            raise ValueError(message)
        return _observation(
            bsns_year,
            reprt_code,
            fs_div,
            missing=(bsns_year, reprt_code) in self.missing_periods,
        )

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeStore:
    saved: int = 0
    skipped: int = 0
    started: int = 0
    succeeded: int = 0
    failures: list[str] = field(default_factory=list)
    save_results: dict[str, bool] = field(default_factory=dict)

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None:
        _ = (target, started_at)
        self.started += 1

    async def save_observation(self, observation: FinancialReportObservation) -> bool:
        if observation.report is None:
            self.skipped += 1
            return False
        self.saved += 1
        return True

    async def mark_succeeded(self, target: InstrumentTarget, completed_at: datetime) -> None:
        _ = (target, completed_at)
        self.succeeded += 1

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        _ = (target, failed_at, error_message)
        self.failures.append(error_code)

    async def close(self) -> None:
        return None


def test_collector_requests_both_divisions_and_reports_skipped_periods() -> None:
    async def run() -> None:
        source = FakeSource(missing_periods=frozenset({(2026, ReportCode.THIRD_QUARTER)}))
        store = FakeStore()
        collector = FinancialStatementCollector(source, store)
        periods = (
            ReportPeriod(2025, ReportCode.ANNUAL),
            ReportPeriod(2026, ReportCode.THIRD_QUARTER),
        )

        result = await collector.collect(_TARGET, periods, _NOW)

        assert len(source.requests) == 4
        assert {entry[2] for entry in source.requests} == {
            FsDivision.CONSOLIDATED,
            FsDivision.SEPARATE,
        }
        assert result.saved == 2
        assert result.skipped == 2
        assert store.started == 1
        assert store.succeeded == 1

    anyio.run(run)


def test_collector_marks_failure_and_reraises() -> None:
    async def run() -> None:
        source = FakeSource(fail_on=(2025, ReportCode.ANNUAL))
        store = FakeStore()
        collector = FinancialStatementCollector(source, store)

        with pytest.raises(ValueError, match="테스트"):
            _ = await collector.collect(_TARGET, (ReportPeriod(2025, ReportCode.ANNUAL),), _NOW)

        assert store.failures == ["ValueError"]
        assert store.succeeded == 0

    anyio.run(run)
