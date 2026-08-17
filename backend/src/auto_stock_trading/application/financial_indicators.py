from typing import TYPE_CHECKING

from auto_stock_trading.domain.fundamentals.financial_statements import ReportCode
from auto_stock_trading.domain.fundamentals.indicators import compute_annual_indicators

if TYPE_CHECKING:
    from auto_stock_trading.application.financial_statements import FinancialReportReader
    from auto_stock_trading.domain.fundamentals.financial_statements import FsDivision
    from auto_stock_trading.domain.fundamentals.indicators import AnnualIndicators


async def annual_indicator_history(
    reader: FinancialReportReader,
    symbol: str,
    fs_div: FsDivision,
) -> tuple[AnnualIndicators, ...]:
    reports = await reader.read_current_reports(symbol)
    annual_reports = sorted(
        (
            report
            for report in reports
            if report.reprt_code is ReportCode.ANNUAL and report.fs_div is fs_div
        ),
        key=lambda report: report.bsns_year,
    )
    results: list[AnnualIndicators] = []
    for report in annual_reports:
        lines = await reader.read_report_lines(report.report_id)
        results.append(compute_annual_indicators(report, lines))
    return tuple(results)
