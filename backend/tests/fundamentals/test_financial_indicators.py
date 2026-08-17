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
from auto_stock_trading.domain.fundamentals.indicators import (
    IndicatorUnavailableReason,
    compute_annual_indicators,
)

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


def _line(
    line_seq: int,
    sj_div: StatementDivision,
    account_id: str | None,
    account_nm: str,
    *,
    amounts: tuple[str | None, str | None],
) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=line_seq,
        sj_div=sj_div,
        account_id=account_id,
        account_nm=account_nm,
        account_detail=None,
        ord=line_seq,
        thstrm_nm="제 57 기",
        thstrm_amount=None if amounts[0] is None else Decimal(amounts[0]),
        frmtrm_nm="제 56 기",
        frmtrm_amount=None if amounts[1] is None else Decimal(amounts[1]),
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )


def _full_lines() -> tuple[FinancialStatementLine, ...]:
    bs = StatementDivision.BALANCE_SHEET
    is_ = StatementDivision.INCOME_STATEMENT
    return (
        _line(1, bs, "ifrs-full_CurrentAssets", "유동자산", amounts=("900", "700")),
        _line(2, bs, "ifrs-full_Assets", "자산총계", amounts=("2200", "1800")),
        _line(3, bs, "ifrs-full_CurrentLiabilities", "유동부채", amounts=("600", "500")),
        _line(4, bs, "ifrs-full_Liabilities", "부채총계", amounts=("800", "850")),
        _line(
            5,
            bs,
            "ifrs-full_EquityAttributableToOwnersOfParent",
            "지배기업 소유주지분",
            amounts=("1050", "950"),
        ),
        _line(6, bs, "ifrs-full_Equity", "자본총계", amounts=("1600", "950")),
        _line(7, is_, "ifrs-full_Revenue", "매출액", amounts=("1200", "1000")),
        _line(8, is_, "dart_OperatingIncomeLoss", "영업이익", amounts=("150", "100")),
        _line(9, is_, "ifrs-full_ProfitLoss", "당기순이익", amounts=("110", "88")),
        _line(
            10,
            is_,
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업 소유주지분",
            amounts=("100", "80"),
        ),
    )


def _indicator_values(lines: tuple[FinancialStatementLine, ...]) -> dict[str, Decimal | None]:
    annual = compute_annual_indicators(_report(), lines)
    return {indicator.key: indicator.value for indicator in annual.indicators}


def _indicator_reasons(
    lines: tuple[FinancialStatementLine, ...],
) -> dict[str, IndicatorUnavailableReason | None]:
    annual = compute_annual_indicators(_report(), lines)
    return {indicator.key: indicator.unavailable_reason for indicator in annual.indicators}


def test_computes_all_indicators_from_a_complete_annual_report() -> None:
    values = _indicator_values(_full_lines())

    assert values == {
        "revenue_growth": Decimal("20.00"),
        "operating_income_growth": Decimal("50.00"),
        "net_income_growth": Decimal("25.00"),
        "operating_margin": Decimal("12.50"),
        "net_margin": Decimal("9.17"),
        "roe": Decimal("10.00"),
        "roa": Decimal("5.50"),
        "debt_ratio": Decimal("50.00"),
        "current_ratio": Decimal("150.00"),
    }


def test_growth_against_a_negative_prior_amount_uses_absolute_denominator() -> None:
    lines = tuple(
        _line(line.line_seq, line.sj_div, line.account_id, line.account_nm, amounts=("50", "-100"))
        if line.account_id == "dart_OperatingIncomeLoss"
        else line
        for line in _full_lines()
    )

    values = _indicator_values(lines)

    assert values["operating_income_growth"] == Decimal("150.00")


def test_reports_figures_with_current_amounts_and_sources() -> None:
    annual = compute_annual_indicators(_report(), _full_lines())

    figures = {figure.key: (figure.account_id, figure.amount) for figure in annual.figures}
    assert figures == {
        "revenue": ("ifrs-full_Revenue", Decimal(1200)),
        "operating_income": ("dart_OperatingIncomeLoss", Decimal(150)),
        "net_income": ("ifrs-full_ProfitLoss", Decimal(110)),
        "net_income_owners": (
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            Decimal(100),
        ),
        "assets": ("ifrs-full_Assets", Decimal(2200)),
        "liabilities": ("ifrs-full_Liabilities", Decimal(800)),
        "equity": ("ifrs-full_Equity", Decimal(1600)),
    }
    assert annual.bsns_year == 2025
    assert annual.rcept_no == "20260310000001"


def test_every_indicator_carries_formula_and_resolved_inputs() -> None:
    annual = compute_annual_indicators(_report(), _full_lines())

    roe = next(indicator for indicator in annual.indicators if indicator.key == "roe")
    assert "지배주주순이익" in roe.formula
    inputs = {(item.period.value, item.account_id): item.amount for item in roe.inputs}
    assert inputs == {
        ("thstrm", "ifrs-full_ProfitLossAttributableToOwnersOfParent"): Decimal(100),
        ("frmtrm", "ifrs-full_EquityAttributableToOwnersOfParent"): Decimal(950),
        ("thstrm", "ifrs-full_EquityAttributableToOwnersOfParent"): Decimal(1050),
    }


def test_missing_account_fails_closed_for_dependent_indicators_only() -> None:
    lines = tuple(line for line in _full_lines() if line.account_id != "ifrs-full_Revenue")

    values = _indicator_values(lines)
    reasons = _indicator_reasons(lines)

    assert values["revenue_growth"] is None
    assert reasons["revenue_growth"] is IndicatorUnavailableReason.MISSING_ACCOUNT
    assert values["operating_margin"] is None
    assert values["net_margin"] is None
    assert values["roe"] == Decimal("10.00")
    assert values["debt_ratio"] == Decimal("50.00")


def test_missing_account_leaves_the_figure_amount_empty() -> None:
    lines = tuple(line for line in _full_lines() if line.account_id != "ifrs-full_Revenue")

    annual = compute_annual_indicators(_report(), lines)

    revenue = next(figure for figure in annual.figures if figure.key == "revenue")
    assert revenue.amount is None


def test_missing_prior_amount_fails_closed_with_reason() -> None:
    lines = tuple(
        _line(line.line_seq, line.sj_div, line.account_id, line.account_nm, amounts=("1200", None))
        if line.account_id == "ifrs-full_Revenue"
        else line
        for line in _full_lines()
    )

    values = _indicator_values(lines)
    reasons = _indicator_reasons(lines)

    assert values["revenue_growth"] is None
    assert reasons["revenue_growth"] is IndicatorUnavailableReason.MISSING_AMOUNT
    assert values["operating_margin"] == Decimal("12.50")


def test_zero_denominator_fails_closed_with_reason() -> None:
    lines = tuple(
        _line(line.line_seq, line.sj_div, line.account_id, line.account_nm, amounts=("1200", "0"))
        if line.account_id == "ifrs-full_Revenue"
        else line
        for line in _full_lines()
    )

    reasons = _indicator_reasons(lines)

    assert reasons["revenue_growth"] is IndicatorUnavailableReason.ZERO_DENOMINATOR


def test_duplicated_account_in_the_same_statement_is_ambiguous() -> None:
    duplicate = _line(
        11,
        StatementDivision.INCOME_STATEMENT,
        "ifrs-full_Revenue",
        "매출액",
        amounts=("999", "999"),
    )
    lines = (*_full_lines(), duplicate)

    values = _indicator_values(lines)
    reasons = _indicator_reasons(lines)

    assert values["revenue_growth"] is None
    assert reasons["revenue_growth"] is IndicatorUnavailableReason.AMBIGUOUS_ACCOUNT
    assert reasons["operating_income_growth"] is None


def test_matching_requires_the_statement_division_not_just_the_account_id() -> None:
    lines = tuple(
        _line(
            line.line_seq,
            StatementDivision.CASH_FLOW,
            line.account_id,
            line.account_nm,
            amounts=("1200", "1000"),
        )
        if line.account_id == "ifrs-full_Revenue"
        else line
        for line in _full_lines()
    )

    reasons = _indicator_reasons(lines)

    assert reasons["revenue_growth"] is IndicatorUnavailableReason.MISSING_ACCOUNT
