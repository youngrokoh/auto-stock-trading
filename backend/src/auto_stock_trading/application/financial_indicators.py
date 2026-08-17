from typing import TYPE_CHECKING

from auto_stock_trading.domain.fundamentals.financial_statements import ReportCode
from auto_stock_trading.domain.fundamentals.indicators import compute_annual_indicators
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
) -> tuple[AnnualIndicators, ...]:
    results: list[AnnualIndicators] = []
    for report in await _annual_reports(reader, symbol, fs_div):
        lines = await reader.read_report_lines(report.report_id)
        results.append(compute_annual_indicators(report, lines))
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
