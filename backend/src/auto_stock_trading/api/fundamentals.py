from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from auto_stock_trading.api.fundamentals_models import (
    FinancialReportDetailResponse,
    FinancialReportResponse,
    FinancialReportsResponse,
    FinancialStatementLineResponse,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    VersionedFinancialReport,
)

if TYPE_CHECKING:
    from auto_stock_trading.application.financial_statements import FinancialReportReader
    from auto_stock_trading.application.market_data import MarketDataReader


def create_fundamentals_router(
    instruments: MarketDataReader,
    reports: FinancialReportReader,
) -> APIRouter:
    router = APIRouter(prefix="/api/fundamentals", tags=["fundamentals"])

    async def financial_reports(symbol: str) -> FinancialReportsResponse:
        results = await reports.read_current_reports(symbol)
        if not results and await instruments.instrument(symbol) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        return FinancialReportsResponse(
            symbol=symbol,
            reports=tuple(_report_response(result) for result in results),
        )

    async def financial_report_history(
        symbol: str,
        bsns_year: int,
        reprt_code: ReportCode,
        fs_div: FsDivision,
    ) -> FinancialReportsResponse:
        results = await reports.read_report_history(symbol, bsns_year, reprt_code, fs_div)
        if not results and await instruments.instrument(symbol) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        return FinancialReportsResponse(
            symbol=symbol,
            reports=tuple(_report_response(result) for result in results),
        )

    async def financial_report_detail(report_id: UUID) -> FinancialReportDetailResponse:
        report = await reports.read_report(report_id)
        if report is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Financial report not found")
        lines = await reports.read_report_lines(report_id)
        return FinancialReportDetailResponse(
            report=_report_response(report),
            lines=tuple(_line_response(line) for line in lines),
        )

    router.add_api_route(
        "/instruments/{symbol}/financial-reports",
        financial_reports,
        methods=["GET"],
        description=(
            "종목의 현재 버전 재무 보고서 목록을 반환한다. 각 보고서는 근거 공시 "
            "접수번호(rcept_no)와 연결·개별 구분(fs_div)을 포함하며 정정 공시는 "
            "이전 버전을 보존한 새 버전으로 나타난다."
        ),
    )
    router.add_api_route(
        "/instruments/{symbol}/financial-reports/history",
        financial_report_history,
        methods=["GET"],
        description="논리 보고서(사업연도·유형·연결구분)의 정정 이력 전체를 버전 순으로 반환한다.",
    )
    router.add_api_route(
        "/financial-reports/{report_id}",
        financial_report_detail,
        methods=["GET"],
        description=(
            "보고서 버전의 계정 라인을 재무제표 구분(sj_div)과 원문 순서(ord)대로 반환한다. "
            "금액은 원문 그대로이며 파생·환산하지 않는다."
        ),
    )
    return router


def _report_response(result: VersionedFinancialReport) -> FinancialReportResponse:
    return FinancialReportResponse(
        report_id=result.report_id,
        symbol=result.symbol,
        corp_code=result.corp_code,
        bsns_year=result.bsns_year,
        reprt_code=result.reprt_code.value,
        fs_div=result.fs_div.value,
        rcept_no=result.rcept_no,
        currency=result.currency,
        received_at=result.received_at,
        version=result.version,
        valid_from=result.valid_from,
        superseded_at=result.superseded_at,
    )


def _line_response(line: FinancialStatementLine) -> FinancialStatementLineResponse:
    return FinancialStatementLineResponse(
        line_seq=line.line_seq,
        sj_div=line.sj_div.value,
        account_id=line.account_id,
        account_nm=line.account_nm,
        account_detail=line.account_detail,
        ord=line.ord,
        thstrm_nm=line.thstrm_nm,
        thstrm_amount=line.thstrm_amount,
        frmtrm_nm=line.frmtrm_nm,
        frmtrm_amount=line.frmtrm_amount,
        bfefrmtrm_nm=line.bfefrmtrm_nm,
        bfefrmtrm_amount=line.bfefrmtrm_amount,
    )
