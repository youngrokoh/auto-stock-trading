from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

import anyio
import httpx2
import pytest
from pydantic import SecretStr

from auto_stock_trading.adapters.disclosures.dart_cash_dividend import DartContractError
from auto_stock_trading.adapters.disclosures.opendart_financials import (
    DART_FINANCIALS_ENDPOINT,
    DartFinancialStatementAdapter,
    FinancialStatementTarget,
)
from auto_stock_trading.adapters.disclosures.opendart_http import DartHttpClient
from auto_stock_trading.application.financial_statements import SourceQuotaExceededError
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FsDivision,
    ReportCode,
    StatementDivision,
)

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "dart"
_TARGET = FinancialStatementTarget(symbol="005930", corp_code="00126380")


class FinancialFixtureHandler:
    requests: list[httpx2.Request]
    _filename: str

    def __init__(self, filename: str) -> None:
        self.requests = []
        self._filename = filename

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        query = parse_qs(request.url.query.decode())
        if not query.get("crtfc_key") or request.url.path != DART_FINANCIALS_ENDPOINT:
            return httpx2.Response(400, request=request)
        return httpx2.Response(
            200,
            request=request,
            headers={"Content-Type": "application/json"},
            text=(_FIXTURE_ROOT / self._filename).read_text(encoding="utf-8"),
        )


def _adapter(filename: str) -> tuple[DartFinancialStatementAdapter, FinancialFixtureHandler]:
    handler = FinancialFixtureHandler(filename)
    client = httpx2.AsyncClient(
        base_url="https://dart.example.test",
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
    )
    return DartFinancialStatementAdapter(
        DartHttpClient(client, SecretStr("fixture-dart-key")),
        _TARGET,
    ), handler


def test_financial_report_is_parsed_with_receipt_evidence() -> None:
    async def run() -> None:
        adapter, handler = _adapter("fnltt_005930_2025_11011_cfs.json")
        try:
            observation = await adapter.fetch_report(
                2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED
            )
        finally:
            await adapter.close()

        report = observation.report
        assert report is not None
        assert report.symbol == "005930"
        assert report.corp_code == "00126380"
        assert report.bsns_year == 2025
        assert report.reprt_code is ReportCode.ANNUAL
        assert report.fs_div is FsDivision.CONSOLIDATED
        assert report.rcept_no == "20260310002820"
        assert report.currency == "KRW"
        assert len(report.lines) == 5
        assets = report.lines[0]
        assert assets.line_seq == 1
        assert assets.sj_div is StatementDivision.BALANCE_SHEET
        assert assets.account_id == "ifrs-full_Assets"
        assert assets.thstrm_amount == Decimal(566942110000000)
        assert assets.bfefrmtrm_amount == Decimal(455905980000000)
        unmapped = report.lines[2]
        assert unmapped.account_id is None
        assert unmapped.thstrm_amount is None
        negative = report.lines[3]
        assert negative.thstrm_amount == Decimal(-77857494000000)
        equity = report.lines[4]
        assert equity.account_detail == "연결자본 | 지배기업 소유주지분"
        assert observation.raw.request_fingerprint == "dart:financials:00126380:2025:11011:CFS"
        assert "crtfc_key" not in observation.raw.payload_json
        query = parse_qs(handler.requests[0].url.query.decode())
        assert query["fs_div"] == ["CFS"]
        assert query["reprt_code"] == ["11011"]

    anyio.run(run)


def test_missing_report_is_skipped_without_normalized_rows() -> None:
    async def run() -> None:
        adapter, _ = _adapter("fnltt_no_data.json")
        try:
            observation = await adapter.fetch_report(
                2026, ReportCode.THIRD_QUARTER, FsDivision.SEPARATE
            )
        finally:
            await adapter.close()

        assert observation.report is None
        assert observation.raw.payload_json != ""

    anyio.run(run)


def test_contract_violations_fail_closed() -> None:
    async def run() -> None:
        bad_amount, _ = _adapter("fnltt_bad_amount.json")
        try:
            with pytest.raises(DartContractError):
                _ = await bad_amount.fetch_report(2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED)
        finally:
            await bad_amount.close()

        mixed, _ = _adapter("fnltt_mixed_receipt.json")
        try:
            with pytest.raises(DartContractError):
                _ = await mixed.fetch_report(2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED)
        finally:
            await mixed.close()

    anyio.run(run)


def test_request_quota_exhaustion_is_distinct_from_a_contract_violation() -> None:
    """일 요청 한도 초과(020)는 종목 실패가 아니라 스윕 중단 사유다(계약 §유니버스 6)."""

    async def run() -> None:
        adapter, _ = _adapter("fnltt_quota_exceeded.json")
        try:
            with pytest.raises(SourceQuotaExceededError):
                _ = await adapter.fetch_report(2025, ReportCode.ANNUAL, FsDivision.CONSOLIDATED)
        finally:
            await adapter.close()

    anyio.run(run)
