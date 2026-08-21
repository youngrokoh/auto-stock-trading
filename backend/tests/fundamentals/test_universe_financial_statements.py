"""유니버스 재무제표 수집 스윕(재무제표 계약 §유니버스 수집 규칙).

계약이 요구하는 네 가지를 고정한다: 매핑 없는 종목은 요청하지 않고 보고, 종목 실패는
스윕을 멈추지 않음, 요청 제한 초과는 즉시 중단하고 미처리 종목을 보고, 이어받기는
현재 버전이 있는 조합만 건너뛴다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final
from uuid import uuid4

import anyio

from auto_stock_trading.application.financial_statements import (
    FinancialCollection,
    ReportPeriod,
    SourceQuotaExceededError,
)
from auto_stock_trading.application.financial_statements_universe import (
    UniverseStatementCollection,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FsDivision,
    ReportCode,
    VersionedFinancialReport,
)
from auto_stock_trading.domain.market_data.corp_codes import DartCorpCode

_NOW = datetime(2026, 8, 21, 1, 0, tzinfo=UTC)
_PERIODS = (
    ReportPeriod(2025, ReportCode.ANNUAL),
    ReportPeriod(2026, ReportCode.HALF_YEAR),
)


def _code(symbol: str, corp_code: str) -> DartCorpCode:
    return DartCorpCode(
        symbol=symbol,
        corp_code=corp_code,
        corp_name=f"테스트{symbol}",
        source="DART",
        received_at=_NOW,
    )


@final
@dataclass
class FakeCodes:
    symbols: tuple[str, ...]
    codes: tuple[DartCorpCode, ...]

    async def universe_symbols(self) -> tuple[str, ...]:
        return self.symbols

    async def universe_corp_codes(self) -> tuple[DartCorpCode, ...]:
        return self.codes


@final
@dataclass
class FakeSymbolCollector:
    saved_per_symbol: int = 2
    fail_on: str | None = None
    quota_on: str | None = None
    calls: list[tuple[str, str, frozenset[tuple[int, str, str]]]] = field(default_factory=list)

    async def collect_symbol(
        self,
        symbol: str,
        corp_code: str,
        periods: tuple[ReportPeriod, ...],
        now: datetime,
        skip: frozenset[tuple[int, str, str]],
    ) -> FinancialCollection:
        _ = (periods, now)
        self.calls.append((symbol, corp_code, skip))
        if symbol == self.quota_on:
            status = "020"
            raise SourceQuotaExceededError(status)
        if symbol == self.fail_on:
            message = "테스트 계약 위반"
            raise ValueError(message)
        return FinancialCollection(saved=self.saved_per_symbol, skipped=1, existing=len(skip))

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeCurrentReports:
    stored: dict[str, tuple[tuple[int, ReportCode, FsDivision], ...]] = field(default_factory=dict)

    async def read_current_reports(self, symbol: str) -> tuple[VersionedFinancialReport, ...]:
        return tuple(
            VersionedFinancialReport(
                report_id=uuid4(),
                symbol=symbol,
                corp_code="00000000",
                bsns_year=bsns_year,
                reprt_code=reprt_code,
                fs_div=fs_div,
                rcept_no="20260814003699",
                currency="KRW",
                received_at=_NOW,
                version=1,
                valid_from=_NOW,
                superseded_at=None,
            )
            for bsns_year, reprt_code, fs_div in self.stored.get(symbol, ())
        )


@final
@dataclass
class FakeSweepStatus:
    started: list[str] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    async def mark_sweep_started(self, key: str, started_at: datetime) -> None:
        _ = started_at
        self.started.append(key)

    async def mark_sweep_succeeded(self, key: str, completed_at: datetime) -> None:
        _ = completed_at
        self.succeeded.append(key)

    async def mark_sweep_failed(
        self,
        key: str,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        _ = (failed_at, error_message)
        self.failed.append((key, error_code))


def _collection(
    codes: FakeCodes,
    source: FakeSymbolCollector,
    status: FakeSweepStatus,
    reports: FakeCurrentReports | None = None,
    *,
    only_missing: bool = False,
) -> UniverseStatementCollection:
    return UniverseStatementCollection(
        codes=codes,
        source=source,
        reports=reports or FakeCurrentReports(),
        status=status,
        only_missing=only_missing,
    )


def test_symbols_without_corp_code_are_reported_without_a_request() -> None:
    async def run() -> None:
        codes = FakeCodes(
            symbols=("005930", "000660", "900110"),
            codes=(_code("005930", "00126380"), _code("000660", "00164779")),
        )
        source = FakeSymbolCollector()
        status = FakeSweepStatus()

        result = await _collection(codes, source, status).run(_PERIODS, _NOW)

        assert [call[0] for call in source.calls] == ["005930", "000660"]
        assert result.symbols == 2
        assert result.saved == 4
        assert result.skipped == 2
        assert result.missing_corp_codes == ("900110",)
        assert result.failed_symbols == ()
        assert status.succeeded == ["KOSPI200"]

    anyio.run(run)


def test_symbol_failure_is_named_and_does_not_stop_the_sweep() -> None:
    async def run() -> None:
        codes = FakeCodes(
            symbols=("005930", "000660"),
            codes=(_code("005930", "00126380"), _code("000660", "00164779")),
        )
        source = FakeSymbolCollector(fail_on="005930")
        status = FakeSweepStatus()

        result = await _collection(codes, source, status).run(_PERIODS, _NOW)

        assert [call[0] for call in source.calls] == ["005930", "000660"]
        assert result.failed_symbols == ("005930",)
        assert result.saved == 2
        assert status.failed == [("KOSPI200", "partial_failure")]
        assert status.succeeded == []

    anyio.run(run)


def test_quota_exhaustion_aborts_the_sweep_and_reports_remaining_symbols() -> None:
    async def run() -> None:
        codes = FakeCodes(
            symbols=("005930", "000660", "005380"),
            codes=(
                _code("005930", "00126380"),
                _code("000660", "00164779"),
                _code("005380", "00164742"),
            ),
        )
        source = FakeSymbolCollector(quota_on="000660")
        status = FakeSweepStatus()

        result = await _collection(codes, source, status).run(_PERIODS, _NOW)

        # 한도가 끝났으면 남은 종목도 모두 실패하므로 요청하지 않는다.
        assert [call[0] for call in source.calls] == ["005930", "000660"]
        assert result.quota_exhausted is True
        assert result.remaining_symbols == ("000660", "005380")
        assert result.failed_symbols == ()
        assert result.saved == 2
        assert status.failed == [("KOSPI200", "quota_exceeded")]

    anyio.run(run)


def test_only_missing_skips_report_keys_that_already_have_a_current_version() -> None:
    async def run() -> None:
        codes = FakeCodes(symbols=("005930",), codes=(_code("005930", "00126380"),))
        source = FakeSymbolCollector()
        status = FakeSweepStatus()
        reports = FakeCurrentReports(
            stored={
                "005930": (
                    (2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED),
                    (2025, ReportCode.ANNUAL, FsDivision.SEPARATE),
                )
            }
        )

        result = await _collection(codes, source, status, reports, only_missing=True).run(
            _PERIODS, _NOW
        )

        assert source.calls[0][2] == frozenset(
            {
                (2025, ReportCode.ANNUAL.value, FsDivision.CONSOLIDATED.value),
                (2025, ReportCode.ANNUAL.value, FsDivision.SEPARATE.value),
            }
        )
        assert result.existing == 2

    anyio.run(run)


def test_full_resweep_passes_no_skip_set() -> None:
    async def run() -> None:
        codes = FakeCodes(symbols=("005930",), codes=(_code("005930", "00126380"),))
        source = FakeSymbolCollector()
        reports = FakeCurrentReports(
            stored={"005930": ((2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED),)}
        )

        result = await _collection(codes, source, FakeSweepStatus(), reports).run(_PERIODS, _NOW)

        # 기본값은 전량 재조회다. 정정 공시를 놓치지 않으려면 건너뛰지 않아야 한다.
        assert source.calls[0][2] == frozenset()
        assert result.existing == 0

    anyio.run(run)
