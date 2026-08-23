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
    AccountResolution,
    AmountPeriod,
    IndicatorUnavailableReason,
    compute_annual_indicators,
    relabel_operating_account_basis,
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


def _cis_only_lines() -> tuple[FinancialStatementLine, ...]:
    """손익계산서를 따로 내지 않고 포괄손익계산서만 제출한 회사(실측 147/198)."""
    return tuple(
        _line(
            line.line_seq,
            StatementDivision.COMPREHENSIVE_INCOME,
            line.account_id,
            line.account_nm,
            amounts=(
                None if line.thstrm_amount is None else str(line.thstrm_amount),
                None if line.frmtrm_amount is None else str(line.frmtrm_amount),
            ),
        )
        if line.sj_div is StatementDivision.INCOME_STATEMENT
        else line
        for line in _full_lines()
    )


def test_profit_accounts_fall_back_to_the_comprehensive_income_statement() -> None:
    values = _indicator_values(_cis_only_lines())

    assert values["revenue_growth"] == Decimal("20.00")
    assert values["operating_margin"] == Decimal("12.50")
    assert values["roe"] == Decimal("10.00")


def test_the_used_division_is_reported_not_the_declared_one() -> None:
    annual = compute_annual_indicators(_report(), _cis_only_lines())

    revenue_figure = next(item for item in annual.figures if item.key == "revenue")
    growth = next(item for item in annual.indicators if item.key == "revenue_growth")

    assert revenue_figure.sj_div is StatementDivision.COMPREHENSIVE_INCOME
    assert {item.sj_div for item in growth.inputs} == {StatementDivision.COMPREHENSIVE_INCOME}
    assert (
        next(item for item in annual.figures if item.key == "assets").sj_div
        is StatementDivision.BALANCE_SHEET
    )


def test_the_income_statement_wins_when_both_divisions_carry_the_account() -> None:
    """두 구분에 모두 있는 회사에서 값이 흔들리면 기존 검증값이 무효가 된다."""
    lines = (
        *_full_lines(),
        _line(
            11,
            StatementDivision.COMPREHENSIVE_INCOME,
            "ifrs-full_Revenue",
            "매출액",
            amounts=("9999", "9999"),
        ),
    )

    annual = compute_annual_indicators(_report(), lines)
    growth = next(item for item in annual.indicators if item.key == "revenue_growth")

    assert growth.value == Decimal("20.00")
    assert {item.sj_div for item in growth.inputs} == {StatementDivision.INCOME_STATEMENT}


def test_ambiguity_is_judged_inside_the_division_actually_used() -> None:
    lines = (
        *_full_lines(),
        _line(
            11,
            StatementDivision.COMPREHENSIVE_INCOME,
            "ifrs-full_Revenue",
            "매출액",
            amounts=("111", "111"),
        ),
        _line(
            12,
            StatementDivision.COMPREHENSIVE_INCOME,
            "ifrs-full_Revenue",
            "매출액",
            amounts=("222", "222"),
        ),
    )

    reasons = _indicator_reasons(lines)

    assert reasons["revenue_growth"] is None


def test_neither_division_carrying_the_account_reports_the_declared_division() -> None:
    lines = tuple(line for line in _full_lines() if line.account_id != "ifrs-full_Revenue")

    annual = compute_annual_indicators(_report(), lines)
    growth = next(item for item in annual.indicators if item.key == "revenue_growth")

    assert growth.unavailable_reason is IndicatorUnavailableReason.MISSING_ACCOUNT
    assert {item.sj_div for item in growth.inputs} == {StatementDivision.INCOME_STATEMENT}


def _financial_issuer_lines() -> tuple[FinancialStatementLine, ...]:
    """금융업 실측 구조: 매출액·영업이익 표준계정이 없고 순이익·자본 계정은 있다."""
    return tuple(
        line
        for line in _cis_only_lines()
        if line.account_id not in ("ifrs-full_Revenue", "dart_OperatingIncomeLoss")
    )


def test_operating_account_indicators_are_relabelled_for_financial_issuers() -> None:
    annual = compute_annual_indicators(_report(), _financial_issuer_lines())

    relabelled = relabel_operating_account_basis(annual)
    reasons = {item.key: item.unavailable_reason for item in relabelled.indicators}

    # 매출액·영업이익을 입력으로 쓰는 지표만 업종 기준 사유로 바뀐다.
    assert reasons["revenue_growth"] is IndicatorUnavailableReason.SECTOR_ACCOUNT_BASIS
    assert reasons["operating_income_growth"] is IndicatorUnavailableReason.SECTOR_ACCOUNT_BASIS
    assert reasons["operating_margin"] is IndicatorUnavailableReason.SECTOR_ACCOUNT_BASIS
    assert reasons["net_margin"] is IndicatorUnavailableReason.SECTOR_ACCOUNT_BASIS
    # 당기순이익·자본 기반 지표는 금융업에서도 계산되므로 건드리지 않는다.
    assert reasons["net_income_growth"] is None
    assert reasons["roe"] is None
    assert reasons["debt_ratio"] is None


def test_relabelling_never_invents_a_value() -> None:
    annual = compute_annual_indicators(_report(), _financial_issuer_lines())

    relabelled = relabel_operating_account_basis(annual)

    values = {item.key: item.value for item in relabelled.indicators}
    assert values["revenue_growth"] is None
    assert values["operating_margin"] is None


def test_relabelling_leaves_other_failure_reasons_alone() -> None:
    """금액이 비어 있거나 모호한 계정은 업종 문제가 아니므로 사유를 바꾸지 않는다."""
    lines = tuple(
        _line(line.line_seq, line.sj_div, line.account_id, line.account_nm, amounts=(None, None))
        if line.account_id == "ifrs-full_Revenue"
        else line
        for line in _full_lines()
    )

    relabelled = relabel_operating_account_basis(compute_annual_indicators(_report(), lines))
    reasons = {item.key: item.unavailable_reason for item in relabelled.indicators}

    assert reasons["revenue_growth"] is IndicatorUnavailableReason.MISSING_AMOUNT


def test_relabelling_keeps_computed_indicators_untouched() -> None:
    annual = compute_annual_indicators(_report(), _full_lines())

    relabelled = relabel_operating_account_basis(annual)

    assert relabelled == annual


def test_the_legacy_ifrs_prefix_is_the_same_account() -> None:
    """실측: 2018년 이전 보고서는 `ifrs_`, 2019년 이후는 `ifrs-full_` 접두를 쓴다.

    IFRS 택소노미 개정으로 접두만 바뀌었고 계정의 의미는 같다. 접두를 구분해 읽으면 과거
    보고서에서 아무 계정도 매칭되지 않는다 — 2026-08-23 실측으로 FY2016~2018 연간 연결 보고서
    432건 중 ROE·EPS가 둘 다 계산되던 것은 9건(2.1%)뿐이었고, 정규화 후 78/109/113건이 됐다.
    """
    lines = tuple(
        _line(
            line.line_seq,
            line.sj_div,
            None if line.account_id is None else line.account_id.replace("ifrs-full_", "ifrs_"),
            line.account_nm,
            amounts=(
                None if line.thstrm_amount is None else str(line.thstrm_amount),
                None if line.frmtrm_amount is None else str(line.frmtrm_amount),
            ),
        )
        for line in _full_lines()
    )

    values = _indicator_values(lines)

    assert values["revenue_growth"] == Decimal("20.00")
    assert values["roe"] == Decimal("10.00")
    assert values["debt_ratio"] == Decimal("50.00")


def test_a_dart_prefixed_account_is_unchanged_by_the_normalisation() -> None:
    values = _indicator_values(_full_lines())

    # 영업이익은 `dart_` 접두이며 정규화 대상이 아니다.
    assert values["operating_margin"] == Decimal("12.50")


def _without(
    lines: tuple[FinancialStatementLine, ...],
    account_id: str,
) -> tuple[FinancialStatementLine, ...]:
    return tuple(line for line in lines if line.account_id != account_id)


def _named(
    line_seq: int,
    sj_div: StatementDivision,
    account_nm: str,
    *,
    amounts: tuple[str | None, str | None],
) -> FinancialStatementLine:
    """표준 계정 ID 없이 계정명만 있는 행. 과거 보고서의 실제 표기다."""
    return _line(line_seq, sj_div, None, account_nm, amounts=amounts)


def test_the_owners_share_of_profit_is_resolved_by_the_decomposition_identity() -> None:
    """계정명이 같은 두 후보 중 항등식을 만족하는 하나만 채택한다(2026-08-23 승인).

    실측: 지배주주순이익 표준계정 결측 111건 중 33건이 같은 이름 두 행이었고, 하나는 당기순이익
    지배주주분, 하나는 총포괄손익 지배주주분이다. 이름으로는 구분할 수 없다.
    """
    is_ = StatementDivision.INCOME_STATEMENT
    lines = (
        *_without(_full_lines(), "ifrs-full_ProfitLossAttributableToOwnersOfParent"),
        # 당기순이익 110 = 지배주주 100 + 비지배 10 (항등식 성립)
        _named(20, is_, "지배기업 소유주지분", amounts=("100", "80")),
        _named(21, is_, "비지배지분", amounts=("10", "8")),
        # 총포괄손익 분해. 같은 이름이지만 합이 당기순이익과 맞지 않는다.
        _named(22, is_, "지배기업 소유주지분", amounts=("130", "90")),
        _named(23, is_, "비지배지분", amounts=("12", "9")),
    )

    annual = compute_annual_indicators(_report(), lines)
    values = {item.key: item.value for item in annual.indicators}
    roe = next(item for item in annual.indicators if item.key == "roe")

    assert values["roe"] == Decimal("10.00")
    numerator = next(item for item in roe.inputs if item.name == "지배주주순이익")
    assert numerator.amount == Decimal(100)
    assert numerator.resolution is AccountResolution.IDENTITY_VERIFIED


def test_an_identity_satisfied_by_two_candidate_amounts_is_refused() -> None:
    is_ = StatementDivision.INCOME_STATEMENT
    lines = (
        *_without(_full_lines(), "ifrs-full_ProfitLossAttributableToOwnersOfParent"),
        _named(20, is_, "지배기업 소유주지분", amounts=("100", "80")),
        _named(21, is_, "비지배지분", amounts=("10", "8")),
        # 다른 금액인데 짝을 바꾸면 역시 110이 된다. 무엇이 지배주주분인지 결정할 수 없다.
        _named(22, is_, "지배기업 소유주지분", amounts=("60", "40")),
        _named(23, is_, "비지배지분", amounts=("50", "48")),
    )

    reasons = _indicator_reasons(lines)

    assert reasons["roe"] is IndicatorUnavailableReason.MISSING_ACCOUNT


def test_a_candidate_that_no_identity_supports_is_refused() -> None:
    is_ = StatementDivision.INCOME_STATEMENT
    lines = (
        *_without(_full_lines(), "ifrs-full_ProfitLossAttributableToOwnersOfParent"),
        _named(20, is_, "지배기업 소유주지분", amounts=("130", "90")),
        _named(21, is_, "비지배지분", amounts=("12", "9")),
    )

    reasons = _indicator_reasons(lines)

    assert reasons["roe"] is IndicatorUnavailableReason.MISSING_ACCOUNT


def test_a_standard_tagged_row_is_never_a_name_candidate() -> None:
    """다른 의미의 표준계정을 이름으로 끌어오지 않는다(계약 §복원 규칙 2)."""
    is_ = StatementDivision.INCOME_STATEMENT
    lines = (
        *_without(_full_lines(), "ifrs-full_ProfitLossAttributableToOwnersOfParent"),
        # 총포괄손익 지배주주분은 표준 ID를 달고 있다. 우연히 항등식을 만족해도 후보가 아니다.
        _line(
            20,
            is_,
            "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent",
            "지배기업 소유주지분",
            amounts=("100", "80"),
        ),
        _named(21, is_, "비지배지분", amounts=("10", "8")),
    )

    reasons = _indicator_reasons(lines)

    assert reasons["roe"] is IndicatorUnavailableReason.MISSING_ACCOUNT


def test_a_blank_amount_on_the_standard_row_is_not_restored() -> None:
    """원문이 그 계정에 대해 말을 했고 값이 없다. 다른 경로로 값을 만들지 않는다."""
    is_ = StatementDivision.INCOME_STATEMENT
    lines = (
        *tuple(
            _line(
                line.line_seq, line.sj_div, line.account_id, line.account_nm, amounts=(None, None)
            )
            if line.account_id == "ifrs-full_ProfitLossAttributableToOwnersOfParent"
            else line
            for line in _full_lines()
        ),
        _named(20, is_, "지배기업 소유주지분", amounts=("100", "80")),
        _named(21, is_, "비지배지분", amounts=("10", "8")),
    )

    reasons = _indicator_reasons(lines)

    assert reasons["roe"] is IndicatorUnavailableReason.MISSING_AMOUNT


def test_the_owners_equity_is_restored_by_subtracting_standard_accounts() -> None:
    bs = StatementDivision.BALANCE_SHEET
    lines = (
        *_without(_full_lines(), "ifrs-full_EquityAttributableToOwnersOfParent"),
        # 자본총계 1600 - 비지배지분 550 = 1050 (당기), 950 - 0 = 950 (전기)
        _line(20, bs, "ifrs-full_NoncontrollingInterests", "비지배지분", amounts=("550", "0")),
    )

    annual = compute_annual_indicators(_report(), lines)
    values = {item.key: item.value for item in annual.indicators}
    roe = next(item for item in annual.indicators if item.key == "roe")

    assert values["roe"] == Decimal("10.00")
    closing = next(
        item
        for item in roe.inputs
        if item.name == "지배기업 소유주지분" and item.period is AmountPeriod.CURRENT
    )
    assert closing.amount == Decimal(1050)
    assert closing.resolution is AccountResolution.STANDARD_DIFFERENCE


def test_a_directly_matched_account_reports_the_standard_resolution() -> None:
    annual = compute_annual_indicators(_report(), _full_lines())

    roe = next(item for item in annual.indicators if item.key == "roe")
    assert all(item.resolution is AccountResolution.STANDARD_ACCOUNT for item in roe.inputs)
    figures = {figure.key: figure.resolution for figure in annual.figures}
    assert figures["net_income_owners"] is AccountResolution.STANDARD_ACCOUNT
