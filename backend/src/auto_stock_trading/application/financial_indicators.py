from typing import TYPE_CHECKING, Final, Protocol

from auto_stock_trading.domain.fundamentals.financial_statements import ReportCode
from auto_stock_trading.domain.fundamentals.indicators import (
    compute_annual_indicators,
    relabel_operating_account_basis,
)
from auto_stock_trading.domain.fundamentals.valuation import compute_valuation

if TYPE_CHECKING:
    from auto_stock_trading.application.financial_statements import FinancialReportReader
    from auto_stock_trading.application.market_data import MarketDataReader
    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FsDivision,
        VersionedFinancialReport,
    )
    from auto_stock_trading.domain.fundamentals.indicators import AnnualIndicators
    from auto_stock_trading.domain.fundamentals.valuation import Valuation

# KOSPI200 업종 코드 6이 금융업이다. 실측(2026-08-21)으로 이 코드의 22종목이 전부 보험·증권·
# 은행지주·카드이고 다른 업종은 섞이지 않았다. 업종명 원천은 아직 없어 코드를 근거로 쓴다.
_FINANCIAL_SECTOR_CODE: Final = "6"


class SectorSource(Protocol):
    async def sector(self, symbol: str) -> str | None: ...

    async def close(self) -> None: ...


async def _annual_reports(
    reader: FinancialReportReader,
    symbol: str,
    fs_div: FsDivision,
) -> tuple[VersionedFinancialReport, ...]:
    reports = await reader.read_current_reports(symbol)
    return tuple(
        sorted(
            (
                report
                for report in reports
                if report.reprt_code is ReportCode.ANNUAL and report.fs_div is fs_div
            ),
            key=lambda report: report.bsns_year,
        )
    )


async def annual_indicator_history(
    reader: FinancialReportReader,
    symbol: str,
    fs_div: FsDivision,
    sectors: SectorSource | None = None,
) -> tuple[AnnualIndicators, ...]:
    """업종을 알 수 있으면 금융업의 매출·영업이익 기반 실패를 업종 기준 사유로 표기한다."""
    financial_issuer = (
        sectors is not None and await sectors.sector(symbol) == _FINANCIAL_SECTOR_CODE
    )
    results: list[AnnualIndicators] = []
    for report in await _annual_reports(reader, symbol, fs_div):
        lines = await reader.read_report_lines(report.report_id)
        annual = compute_annual_indicators(report, lines)
        results.append(relabel_operating_account_basis(annual) if financial_issuer else annual)
    return tuple(results)


async def valuation_snapshot(
    financials: FinancialReportReader,
    market_data: MarketDataReader,
    symbol: str,
    fs_div: FsDivision,
) -> Valuation | None:
    annual_reports = await _annual_reports(financials, symbol, fs_div)
    if not annual_reports:
        return None
    latest = annual_reports[-1]
    lines = await financials.read_report_lines(latest.report_id)
    quote = await market_data.quote(symbol)
    shares = await market_data.listed_share_count(symbol)
    return compute_valuation(latest, lines, quote, shares)
