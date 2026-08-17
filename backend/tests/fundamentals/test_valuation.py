from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialStatementLine,
    FsDivision,
    ReportCode,
    StatementDivision,
    VersionedFinancialReport,
)
from auto_stock_trading.domain.fundamentals.indicators import IndicatorUnavailableReason
from auto_stock_trading.domain.fundamentals.valuation import compute_valuation
from auto_stock_trading.domain.market_data.listed_shares import VersionedListedShareCount
from auto_stock_trading.domain.market_data.models import Quote

_NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def _report() -> VersionedFinancialReport:
    return VersionedFinancialReport(
        report_id=uuid4(),
        symbol="005930",
        corp_code="00126380",
        bsns_year=2025,
        reprt_code=ReportCode.ANNUAL,
        fs_div=FsDivision.CONSOLIDATED,
        rcept_no="20260310000001",
        currency="KRW",
        received_at=_NOW,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


def _eps_line(thstrm: str | None) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=1,
        sj_div=StatementDivision.INCOME_STATEMENT,
        account_id="ifrs-full_BasicEarningsLossPerShare",
        account_nm="기본주당이익",
        account_detail=None,
        ord=1,
        thstrm_nm="제 57 기",
        thstrm_amount=None if thstrm is None else Decimal(thstrm),
        frmtrm_nm="제 56 기",
        frmtrm_amount=Decimal(8),
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )


def _quote() -> Quote:
    return Quote(
        symbol="005930",
        price=Decimal(220),
        open_price=Decimal(210),
        high_price=Decimal(225),
        low_price=Decimal(205),
        previous_close=Decimal(215),
        change=Decimal(5),
        change_percent=Decimal("2.33"),
        volume=1000,
        trading_value=Decimal(220000),
        currency="KRW",
        source="KIS",
        as_of=_NOW,
        received_at=_NOW,
    )


def _shares() -> VersionedListedShareCount:
    return VersionedListedShareCount(
        symbol="005930",
        share_count=1000,
        source="KIS",
        as_of=_NOW,
        received_at=_NOW,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


def test_computes_eps_per_and_market_cap_with_bases() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _quote(), _shares())

    values = {item.key: item.value for item in valuation.items}
    assert values == {
        "eps": Decimal(11),
        "per": Decimal("20.00"),
        "market_cap": Decimal(220000),
    }
    assert valuation.price is not None
    assert valuation.price.price == Decimal(220)
    assert valuation.price.as_of == _NOW
    assert valuation.share_count is not None
    assert valuation.share_count.share_count == 1000
    assert valuation.report.rcept_no == "20260310000001"
    assert valuation.report.bsns_year == 2025


def test_every_item_carries_a_formula() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _quote(), _shares())

    formulas = {item.key: item.formula for item in valuation.items}
    assert "기본주당이익" in formulas["eps"]
    assert formulas["per"] == "현재가 ÷ 최근 연간 기본주당이익"
    assert formulas["market_cap"] == "현재가 × 보통주 상장주식수"


def test_missing_quote_fails_price_dependent_items_only() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), None, _shares())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    values = {item.key: item.value for item in valuation.items}
    assert values["eps"] == Decimal(11)
    assert reasons["per"] is IndicatorUnavailableReason.MISSING_QUOTE
    assert reasons["market_cap"] is IndicatorUnavailableReason.MISSING_QUOTE
    assert valuation.price is None


def test_missing_share_count_fails_market_cap_only() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _quote(), None)

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    values = {item.key: item.value for item in valuation.items}
    assert values["per"] == Decimal("20.00")
    assert reasons["market_cap"] is IndicatorUnavailableReason.MISSING_SHARE_COUNT
    assert valuation.share_count is None


def test_missing_eps_line_fails_eps_and_per() -> None:
    valuation = compute_valuation(_report(), (), _quote(), _shares())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    values = {item.key: item.value for item in valuation.items}
    assert reasons["eps"] is IndicatorUnavailableReason.MISSING_ACCOUNT
    assert reasons["per"] is IndicatorUnavailableReason.MISSING_ACCOUNT
    assert values["market_cap"] == Decimal(220000)


def test_zero_eps_fails_per_with_zero_denominator() -> None:
    valuation = compute_valuation(_report(), (_eps_line("0"),), _quote(), _shares())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    assert reasons["per"] is IndicatorUnavailableReason.ZERO_DENOMINATOR


def test_empty_eps_amount_fails_with_missing_amount() -> None:
    valuation = compute_valuation(_report(), (_eps_line(None),), _quote(), _shares())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    assert reasons["eps"] is IndicatorUnavailableReason.MISSING_AMOUNT
    assert reasons["per"] is IndicatorUnavailableReason.MISSING_AMOUNT
