from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from auto_stock_trading.api.fundamentals_models import (
    AnnualIndicatorsResponse,
    DisclosureResponse,
    DisclosuresResponse,
    FinancialFigureResponse,
    FinancialIndicatorsResponse,
    FinancialReportDetailResponse,
    FinancialReportResponse,
    FinancialReportsResponse,
    FinancialStatementLineResponse,
    IndicatorInputResponse,
    IndicatorResponse,
    ShareClassResponse,
    ValuationItemResponse,
    ValuationPriceBasisResponse,
    ValuationReportBasisResponse,
    ValuationResponse,
    ValuationShareCountBasisResponse,
)
from auto_stock_trading.application.financial_indicators import (
    SectorSource,
    ShareClassSource,
    annual_indicator_history,
    valuation_snapshot,
)
from auto_stock_trading.domain.fundamentals.disclosures import Disclosure
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    VersionedFinancialReport,
)
from auto_stock_trading.domain.fundamentals.indicators import (
    AnnualIndicators,
    FinancialFigure,
    IndicatorValue,
)
from auto_stock_trading.domain.fundamentals.valuation import Valuation

if TYPE_CHECKING:
    from auto_stock_trading.application.disclosures import DisclosureReader
    from auto_stock_trading.application.financial_statements import FinancialReportReader
    from auto_stock_trading.application.market_data import MarketDataReader


def create_fundamentals_router(
    instruments: MarketDataReader,
    reports: FinancialReportReader,
    disclosures: DisclosureReader,
    sectors: SectorSource,
    share_classes: ShareClassSource,
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

    async def financial_indicators(
        symbol: str,
        fs_div: FsDivision = FsDivision.CONSOLIDATED,
    ) -> FinancialIndicatorsResponse:
        years = await annual_indicator_history(reports, symbol, fs_div, sectors)
        if not years and await instruments.instrument(symbol) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        valuation = await valuation_snapshot(
            reports,
            instruments,
            symbol,
            fs_div,
            share_classes,
        )
        return FinancialIndicatorsResponse(
            symbol=symbol,
            fs_div=fs_div.value,
            years=tuple(_annual_indicators_response(year) for year in years),
            valuation=None if valuation is None else _valuation_response(valuation),
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

    _add_disclosure_route(router, instruments, disclosures)
    router.add_api_route(
        "/instruments/{symbol}/indicators",
        financial_indicators,
        methods=["GET"],
        description=(
            "연간 사업보고서의 현재 버전에서 계산한 성장성·수익성·안정성 지표와 실적 원문 "
            "값을 사업연도 오름차순으로 반환한다. 각 지표는 수식, 입력 계정과 금액, 근거 "
            "접수번호(rcept_no)를 포함하며 필요한 계정이 없으면 값 없이 사유 코드를 담는다. "
            "가치지표는 상장 클래스별 시세·주식수를 결합하며, 우선주가 상장된 회사의 "
            "BPS·PBR은 자본 배분 판단이 필요해 사유와 함께 빈 값이다."
        ),
    )
    return router


def _add_disclosure_route(
    router: APIRouter,
    instruments: MarketDataReader,
    disclosures: DisclosureReader,
) -> None:
    async def instrument_disclosures(symbol: str, limit: int = 30) -> DisclosuresResponse:
        results = await disclosures.read_disclosures(symbol, limit)
        if not results and await instruments.instrument(symbol) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Instrument not found")
        return DisclosuresResponse(
            symbol=symbol,
            disclosures=tuple(_disclosure_response(result) for result in results),
        )

    router.add_api_route(
        "/instruments/{symbol}/disclosures",
        instrument_disclosures,
        methods=["GET"],
        description=(
            "DART 공시 목록 사실을 접수일 내림차순으로 반환한다. 유형은 정기공시(A)·"
            "주요사항보고(B)·지분공시(D)·거래소공시(I)이며, 접수번호로 DART 원문 뷰어에 "
            "연결할 수 있다. 목록 항목은 불변이고 정정 공시는 새 접수번호로 나타난다."
        ),
    )


def _disclosure_response(result: Disclosure) -> DisclosureResponse:
    return DisclosureResponse(
        rcept_no=result.rcept_no,
        report_nm=result.report_nm,
        flr_nm=result.filer_name,
        rcept_dt=result.receipt_date,
        disclosure_type=result.disclosure_type.value,
        received_at=result.received_at,
    )


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


def _annual_indicators_response(annual: AnnualIndicators) -> AnnualIndicatorsResponse:
    return AnnualIndicatorsResponse(
        bsns_year=annual.bsns_year,
        reprt_code=annual.reprt_code.value,
        fs_div=annual.fs_div.value,
        rcept_no=annual.rcept_no,
        currency=annual.currency,
        version=annual.version,
        figures=tuple(_figure_response(figure) for figure in annual.figures),
        indicators=tuple(_indicator_response(indicator) for indicator in annual.indicators),
    )


def _figure_response(figure: FinancialFigure) -> FinancialFigureResponse:
    return FinancialFigureResponse(
        key=figure.key,
        name=figure.name,
        sj_div=figure.sj_div.value,
        account_id=figure.account_id,
        amount=figure.amount,
        resolution=figure.resolution.value,
    )


def _indicator_response(indicator: IndicatorValue) -> IndicatorResponse:
    return IndicatorResponse(
        key=indicator.key,
        name=indicator.name,
        category=indicator.category.value,
        formula=indicator.formula,
        inputs=tuple(
            IndicatorInputResponse(
                name=item.name,
                sj_div=item.sj_div.value,
                account_id=item.account_id,
                period=item.period.value,
                amount=item.amount,
                resolution=item.resolution.value,
            )
            for item in indicator.inputs
        ),
        value=indicator.value,
        unavailable_reason=(
            None if indicator.unavailable_reason is None else indicator.unavailable_reason.value
        ),
    )


def _valuation_response(valuation: Valuation) -> ValuationResponse:
    price = valuation.price
    shares = valuation.share_count
    return ValuationResponse(
        price=(
            None
            if price is None
            else ValuationPriceBasisResponse(
                price=price.price,
                as_of=price.as_of,
                source=price.source,
            )
        ),
        share_count=(
            None
            if shares is None
            else ValuationShareCountBasisResponse(
                share_count=shares.share_count,
                as_of=shares.as_of,
                source=shares.source,
                version=shares.version,
            )
        ),
        report=ValuationReportBasisResponse(
            bsns_year=valuation.report.bsns_year,
            reprt_code=valuation.report.reprt_code.value,
            fs_div=valuation.report.fs_div.value,
            rcept_no=valuation.report.rcept_no,
            version=valuation.report.version,
        ),
        items=tuple(
            ValuationItemResponse(
                key=item.key,
                name=item.name,
                unit=item.unit,
                formula=item.formula,
                value=item.value,
                unavailable_reason=(
                    None if item.unavailable_reason is None else item.unavailable_reason.value
                ),
                resolution=item.resolution.value,
            )
            for item in valuation.items
        ),
        share_classes=tuple(
            ShareClassResponse(
                symbol=entry.symbol,
                class_kind=entry.class_kind.value,
                name=entry.name,
                price=entry.price,
                as_of=entry.as_of,
                volume=entry.volume,
                share_count=entry.share_count,
                share_count_as_of=entry.share_count_as_of,
                market_cap=entry.market_cap,
            )
            for entry in valuation.share_classes
        ),
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
