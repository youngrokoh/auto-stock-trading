from typing import TYPE_CHECKING, Final, Protocol

from auto_stock_trading.domain.fundamentals.financial_statements import ReportCode
from auto_stock_trading.domain.fundamentals.indicators import (
    compute_annual_indicators,
    relabel_operating_account_basis,
)
from auto_stock_trading.domain.fundamentals.valuation import (
    ShareClassQuote,
    compute_valuation,
)
from auto_stock_trading.domain.market_data.share_classes import ShareClassKind

if TYPE_CHECKING:
    from auto_stock_trading.application.financial_statements import FinancialReportReader
    from auto_stock_trading.application.market_data import MarketDataReader
    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FsDivision,
        VersionedFinancialReport,
    )
    from auto_stock_trading.domain.fundamentals.indicators import AnnualIndicators
    from auto_stock_trading.domain.fundamentals.valuation import Valuation
    from auto_stock_trading.domain.market_data.share_classes import ShareClass

# KOSPI200 업종 코드 6이 금융업이다. 실측(2026-08-21)으로 이 코드의 22종목이 전부 보험·증권·
# 은행지주·카드이고 다른 업종은 섞이지 않았다. 업종명 원천은 아직 없어 코드를 근거로 쓴다.
_FINANCIAL_SECTOR_CODE: Final = "6"


class SectorSource(Protocol):
    async def sector(self, symbol: str) -> str | None: ...

    async def close(self) -> None: ...


class ShareClassSource(Protocol):
    async def share_classes(self, common_symbol: str) -> tuple[ShareClass, ...]: ...

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


async def _class_quote(
    market_data: MarketDataReader,
    symbol: str,
    class_kind: ShareClassKind,
    name: str,
) -> ShareClassQuote:
    """클래스 하나의 시세·상장주식수. 없는 값은 그대로 비워 상위가 fail-closed로 판정한다."""
    quote = await market_data.quote(symbol)
    shares = await market_data.listed_share_count(symbol)
    return ShareClassQuote(
        symbol=symbol,
        class_kind=class_kind,
        name=name,
        price=None if quote is None else quote.price,
        as_of=None if quote is None else quote.as_of,
        volume=None if quote is None else quote.volume,
        share_count=None if shares is None else shares.share_count,
        share_count_as_of=None if shares is None else shares.as_of,
        share_count_version=1 if shares is None else shares.version,
    )


async def valuation_snapshot(
    financials: FinancialReportReader,
    market_data: MarketDataReader,
    symbol: str,
    fs_div: FsDivision,
    share_classes: ShareClassSource | None = None,
) -> Valuation | None:
    """가치지표. 클래스 사실이 없으면 `preferred=None`으로 넘겨 모르는 상태를 유지한다."""
    annual_reports = await _annual_reports(financials, symbol, fs_div)
    if not annual_reports:
        return None
    latest = annual_reports[-1]
    lines = await financials.read_report_lines(latest.report_id)
    classes = () if share_classes is None else await share_classes.share_classes(symbol)
    common_name = next(
        (item.name for item in classes if item.class_kind is ShareClassKind.COMMON),
        symbol,
    )
    common = await _class_quote(market_data, symbol, ShareClassKind.COMMON, common_name)
    if not classes:
        return compute_valuation(latest, lines, common, None)
    preferred = [
        await _class_quote(market_data, item.symbol, item.class_kind, item.name)
        for item in classes
        if item.class_kind is ShareClassKind.PREFERRED
    ]
    return compute_valuation(latest, lines, common, tuple(preferred))
