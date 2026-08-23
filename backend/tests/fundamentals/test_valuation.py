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
from auto_stock_trading.domain.fundamentals.valuation import (
    ShareClassQuote,
    compute_valuation,
)
from auto_stock_trading.domain.market_data.models import Quote
from auto_stock_trading.domain.market_data.share_classes import ShareClassKind

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


def _eps_line(
    thstrm: str | None,
    sj_div: StatementDivision = StatementDivision.INCOME_STATEMENT,
) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=1,
        sj_div=sj_div,
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


def _common(
    *,
    price: str | None = "220",
    share_count: int | None = 1000,
) -> ShareClassQuote:
    quote = _quote()
    return ShareClassQuote(
        symbol="005930",
        class_kind=ShareClassKind.COMMON,
        name="삼성전자",
        price=None if price is None else Decimal(price),
        as_of=None if price is None else quote.as_of,
        volume=quote.volume,
        share_count=share_count,
        share_count_as_of=None if share_count is None else quote.as_of,
    )


def test_computes_eps_per_and_market_cap_with_bases() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _common(), ())

    values = {item.key: item.value for item in valuation.items}
    assert values == {
        "eps": Decimal(11),
        "per": Decimal("20.00"),
        "market_cap": Decimal(220000),
        # 우선주가 상장되지 않은 회사라 전종목 합계가 보통주와 같다.
        "market_cap_total": Decimal(220000),
        "bps": None,
        "pbr": None,
    }
    assert valuation.price is not None
    assert valuation.price.price == Decimal(220)
    assert valuation.price.as_of == _NOW
    assert valuation.share_count is not None
    assert valuation.share_count.share_count == 1000
    assert valuation.report.rcept_no == "20260310000001"
    assert valuation.report.bsns_year == 2025


def test_every_item_carries_a_formula() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _common(), ())

    formulas = {item.key: item.formula for item in valuation.items}
    assert "기본주당이익" in formulas["eps"]
    assert formulas["per"] == "보통주 현재가 ÷ 최근 연간 기본주당이익"
    assert formulas["market_cap"] == "보통주 현재가 × 보통주 상장주식수"
    assert formulas["market_cap_total"] == "Σ 클래스별 (현재가 × 상장주식수)"
    assert "지배주주지분" in formulas["bps"]
    assert formulas["pbr"] == "보통주 현재가 ÷ 주당순자산(보통주)"


def test_missing_quote_fails_price_dependent_items_only() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _common(price=None), ())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    values = {item.key: item.value for item in valuation.items}
    assert values["eps"] == Decimal(11)
    assert reasons["per"] is IndicatorUnavailableReason.MISSING_QUOTE
    assert reasons["market_cap"] is IndicatorUnavailableReason.MISSING_QUOTE
    assert valuation.price is None


def test_missing_share_count_fails_market_cap_only() -> None:
    valuation = compute_valuation(_report(), (_eps_line("11"),), _common(share_count=None), ())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    values = {item.key: item.value for item in valuation.items}
    assert values["per"] == Decimal("20.00")
    assert reasons["market_cap"] is IndicatorUnavailableReason.MISSING_SHARE_COUNT
    assert valuation.share_count is None


def test_missing_eps_line_fails_eps_and_per() -> None:
    valuation = compute_valuation(_report(), (), _common(), ())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    values = {item.key: item.value for item in valuation.items}
    assert reasons["eps"] is IndicatorUnavailableReason.MISSING_ACCOUNT
    assert reasons["per"] is IndicatorUnavailableReason.MISSING_ACCOUNT
    assert values["market_cap"] == Decimal(220000)


def test_zero_eps_fails_per_with_zero_denominator() -> None:
    valuation = compute_valuation(_report(), (_eps_line("0"),), _common(), ())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    assert reasons["per"] is IndicatorUnavailableReason.ZERO_DENOMINATOR


def test_empty_eps_amount_fails_with_missing_amount() -> None:
    valuation = compute_valuation(_report(), (_eps_line(None),), _common(), ())

    reasons = {item.key: item.unavailable_reason for item in valuation.items}
    assert reasons["eps"] is IndicatorUnavailableReason.MISSING_AMOUNT
    assert reasons["per"] is IndicatorUnavailableReason.MISSING_AMOUNT


def test_eps_falls_back_to_the_comprehensive_income_statement() -> None:
    """실측 147/198 회사는 기본주당이익을 포괄손익계산서에만 싣는다."""
    valuation = compute_valuation(
        _report(),
        (_eps_line("11", StatementDivision.COMPREHENSIVE_INCOME),),
        _common(),
        (),
    )

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value == Decimal(11)
    assert items["per"].unavailable_reason is None


def _eps_line_of(
    account_id: str,
    thstrm: str | None,
    line_seq: int = 2,
    sj_div: StatementDivision = StatementDivision.COMPREHENSIVE_INCOME,
) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=line_seq,
        sj_div=sj_div,
        account_id=account_id,
        account_nm="주당이익",
        account_detail=None,
        ord=line_seq,
        thstrm_nm="제 57 기",
        thstrm_amount=None if thstrm is None else Decimal(thstrm),
        frmtrm_nm="제 56 기",
        frmtrm_amount=None,
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )


_CONTINUING = "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"
_DISCONTINUED = "ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations"


def test_split_reported_eps_is_the_sum_of_continuing_and_discontinued() -> None:
    """실측(태광산업): 계속 +33,256 / 중단 -55,240 이라 계속영업만 쓰면 적자가 흑자로 보인다."""
    lines = (
        _eps_line_of(_CONTINUING, "33256", 1),
        _eps_line_of(_DISCONTINUED, "-55240", 2),
    )

    valuation = compute_valuation(_report(), lines, _common(), ())

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value == Decimal(-21984)


def test_continuing_eps_alone_is_the_total_when_no_discontinued_row_exists() -> None:
    """실측(삼성중공업·롯데쇼핑·효성중공업): 중단영업 관련 행이 원문에 아예 없다."""
    valuation = compute_valuation(
        _report(),
        (_eps_line_of(_CONTINUING, "75", 1),),
        _common(),
        (),
    )

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value == Decimal(75)
    assert items["eps"].unavailable_reason is None


def test_a_discontinued_row_without_an_amount_fails_closed() -> None:
    """실측(씨에스윈드): 중단영업 행은 있고 금액이 공란이다. 0으로 가정하지 않는다."""
    lines = (
        _eps_line_of(_CONTINUING, "480", 1),
        _eps_line_of(_DISCONTINUED, None, 2),
    )

    valuation = compute_valuation(_report(), lines, _common(), ())

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value is None
    assert items["eps"].unavailable_reason is IndicatorUnavailableReason.MISSING_AMOUNT


def test_the_total_eps_account_wins_over_the_split_accounts() -> None:
    lines = (
        _eps_line("6605"),
        _eps_line_of(_CONTINUING, "9999", 2),
        _eps_line_of(_DISCONTINUED, "1111", 3),
    )

    valuation = compute_valuation(_report(), lines, _common(), ())

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value == Decimal(6605)


def test_eps_accepts_the_legacy_ifrs_prefix() -> None:
    """2018년 이전 보고서의 기본주당이익도 같은 계정으로 읽는다."""
    legacy = _eps_line_of("ifrs_BasicEarningsLossPerShare", "6605", 1)

    valuation = compute_valuation(_report(), (legacy,), _common(), ())

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value == Decimal(6605)


def test_a_name_only_basic_eps_row_is_unused_without_share_class_facts() -> None:
    """클래스 사실이 없으면 우선주 유무를 모른다. 모르면 복원하지 않는다.

    2026-08-23 개정으로 **우선주 미상장이 확인된 회사**만 복원한다. 그 경로는
    `test_valuation_preferred.py`가 덮는다.
    """
    named = FinancialStatementLine(
        line_seq=9,
        sj_div=StatementDivision.COMPREHENSIVE_INCOME,
        account_id=None,
        account_nm="보통주 기본주당이익",
        account_detail=None,
        ord=9,
        thstrm_nm="제 57 기",
        thstrm_amount=Decimal(6605),
        frmtrm_nm="제 56 기",
        frmtrm_amount=None,
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )

    valuation = compute_valuation(_report(), (named,), _common(), None)

    items = {item.key: item for item in valuation.items}
    assert items["eps"].value is None
    assert items["eps"].unavailable_reason is IndicatorUnavailableReason.MISSING_ACCOUNT
