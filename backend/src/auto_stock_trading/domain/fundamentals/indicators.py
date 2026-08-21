from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.fundamentals.financial_statements import StatementDivision

if TYPE_CHECKING:
    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialStatementLine,
        FsDivision,
        ReportCode,
        VersionedFinancialReport,
    )


class IndicatorCategory(StrEnum):
    GROWTH = "growth"
    PROFITABILITY = "profitability"
    STABILITY = "stability"


class IndicatorUnavailableReason(StrEnum):
    MISSING_ACCOUNT = "MISSING_ACCOUNT"
    AMBIGUOUS_ACCOUNT = "AMBIGUOUS_ACCOUNT"
    MISSING_AMOUNT = "MISSING_AMOUNT"
    ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
    MISSING_QUOTE = "MISSING_QUOTE"
    MISSING_SHARE_COUNT = "MISSING_SHARE_COUNT"


class AmountPeriod(StrEnum):
    CURRENT = "thstrm"
    PRIOR = "frmtrm"


@dataclass(frozen=True, slots=True)
class IndicatorInput:
    name: str
    sj_div: StatementDivision
    account_id: str
    period: AmountPeriod
    amount: Decimal | None


@dataclass(frozen=True, slots=True)
class IndicatorValue:
    key: str
    name: str
    category: IndicatorCategory
    formula: str
    inputs: tuple[IndicatorInput, ...]
    value: Decimal | None
    unavailable_reason: IndicatorUnavailableReason | None


@dataclass(frozen=True, slots=True)
class FinancialFigure:
    key: str
    name: str
    sj_div: StatementDivision
    account_id: str
    amount: Decimal | None


@dataclass(frozen=True, slots=True)
class AnnualIndicators:
    bsns_year: int
    reprt_code: ReportCode
    fs_div: FsDivision
    rcept_no: str
    currency: str
    version: int
    figures: tuple[FinancialFigure, ...]
    indicators: tuple[IndicatorValue, ...]


@dataclass(frozen=True, slots=True)
class _Account:
    name: str
    # 우선순위 순서다. 앞 구분에서 계정을 찾으면 뒤 구분은 보지 않는다(지표 계약 §입력 계정).
    divisions: tuple[StatementDivision, ...]
    account_id: str


# 손익 계정은 회사의 제출 형식에 따라 IS 또는 CIS에 실린다(실측 51 대 147).
_PROFIT_DIVISIONS: Final = (
    StatementDivision.INCOME_STATEMENT,
    StatementDivision.COMPREHENSIVE_INCOME,
)
_BALANCE_DIVISIONS: Final = (StatementDivision.BALANCE_SHEET,)

_REVENUE = _Account("매출액", _PROFIT_DIVISIONS, "ifrs-full_Revenue")
_OPERATING_INCOME = _Account("영업이익", _PROFIT_DIVISIONS, "dart_OperatingIncomeLoss")
_NET_INCOME = _Account("당기순이익", _PROFIT_DIVISIONS, "ifrs-full_ProfitLoss")
_NET_INCOME_OWNERS = _Account(
    "지배주주순이익",
    _PROFIT_DIVISIONS,
    "ifrs-full_ProfitLossAttributableToOwnersOfParent",
)
_ASSETS = _Account("자산총계", _BALANCE_DIVISIONS, "ifrs-full_Assets")
_LIABILITIES = _Account("부채총계", _BALANCE_DIVISIONS, "ifrs-full_Liabilities")
_EQUITY = _Account("자본총계", _BALANCE_DIVISIONS, "ifrs-full_Equity")
_EQUITY_OWNERS = _Account(
    "지배기업 소유주지분",
    _BALANCE_DIVISIONS,
    "ifrs-full_EquityAttributableToOwnersOfParent",
)
_CURRENT_ASSETS = _Account("유동자산", _BALANCE_DIVISIONS, "ifrs-full_CurrentAssets")
_CURRENT_LIABILITIES = _Account("유동부채", _BALANCE_DIVISIONS, "ifrs-full_CurrentLiabilities")

_FIGURES: tuple[tuple[str, _Account], ...] = (
    ("revenue", _REVENUE),
    ("operating_income", _OPERATING_INCOME),
    ("net_income", _NET_INCOME),
    ("net_income_owners", _NET_INCOME_OWNERS),
    ("assets", _ASSETS),
    ("liabilities", _LIABILITIES),
    ("equity", _EQUITY),
)

_PERCENT_QUANTUM = Decimal("0.01")
_HUNDRED = Decimal(100)
_TWO = Decimal(2)


@dataclass(frozen=True, slots=True)
class _ResolvedInput:
    spec: IndicatorInput
    reason: IndicatorUnavailableReason | None


def _resolve(
    lines: tuple[FinancialStatementLine, ...],
    account: _Account,
    period: AmountPeriod,
) -> _ResolvedInput:
    division, matches = _matching_lines(lines, account)
    amount: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    if len(matches) > 1:
        reason = IndicatorUnavailableReason.AMBIGUOUS_ACCOUNT
    elif not matches:
        reason = IndicatorUnavailableReason.MISSING_ACCOUNT
    else:
        line = matches[0]
        amount = line.thstrm_amount if period is AmountPeriod.CURRENT else line.frmtrm_amount
        if amount is None:
            reason = IndicatorUnavailableReason.MISSING_AMOUNT
    spec = IndicatorInput(
        name=account.name,
        sj_div=division,
        account_id=account.account_id,
        period=period,
        amount=amount,
    )
    return _ResolvedInput(spec=spec, reason=reason)


def _matching_lines(
    lines: tuple[FinancialStatementLine, ...],
    account: _Account,
) -> tuple[StatementDivision, list[FinancialStatementLine]]:
    """실제로 사용한 구분과 그 안의 후보 행을 돌려준다. 모호성은 사용한 구분 안에서만 본다."""
    for division in account.divisions:
        matches = [
            line
            for line in lines
            if line.sj_div is division and line.account_id == account.account_id
        ]
        if matches:
            return division, matches
    return account.divisions[0], []


def _percent(value: Decimal) -> Decimal:
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class _IndicatorResult:
    value: Decimal | None
    reason: IndicatorUnavailableReason | None


def _finish(
    resolved: tuple[_ResolvedInput, ...],
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> _IndicatorResult:
    for item in resolved:
        if item.reason is not None:
            return _IndicatorResult(value=None, reason=item.reason)
    if numerator is None or denominator is None:
        return _IndicatorResult(value=None, reason=IndicatorUnavailableReason.MISSING_AMOUNT)
    if denominator == 0:
        return _IndicatorResult(value=None, reason=IndicatorUnavailableReason.ZERO_DENOMINATOR)
    return _IndicatorResult(value=_percent(numerator / denominator * _HUNDRED), reason=None)


def _growth(
    lines: tuple[FinancialStatementLine, ...],
    key: str,
    name: str,
    account: _Account,
) -> IndicatorValue:
    current = _resolve(lines, account, AmountPeriod.CURRENT)
    prior = _resolve(lines, account, AmountPeriod.PRIOR)
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    if current.spec.amount is not None and prior.spec.amount is not None:
        numerator = current.spec.amount - prior.spec.amount
        denominator = abs(prior.spec.amount)
    result = _finish((current, prior), numerator, denominator)
    formula = f"(당기 {account.name} - 전기 {account.name}) ÷ |전기 {account.name}| × 100"
    return IndicatorValue(
        key=key,
        name=name,
        category=IndicatorCategory.GROWTH,
        formula=formula,
        inputs=(current.spec, prior.spec),
        value=result.value,
        unavailable_reason=result.reason,
    )


def _ratio(
    lines: tuple[FinancialStatementLine, ...],
    key: str,
    name: str,
    *,
    category: IndicatorCategory,
    accounts: tuple[_Account, _Account],
) -> IndicatorValue:
    numerator_account, denominator_account = accounts
    numerator = _resolve(lines, numerator_account, AmountPeriod.CURRENT)
    denominator = _resolve(lines, denominator_account, AmountPeriod.CURRENT)
    result = _finish(
        (numerator, denominator),
        numerator.spec.amount,
        denominator.spec.amount,
    )
    formula = f"당기 {numerator_account.name} ÷ 당기 {denominator_account.name} × 100"
    return IndicatorValue(
        key=key,
        name=name,
        category=category,
        formula=formula,
        inputs=(numerator.spec, denominator.spec),
        value=result.value,
        unavailable_reason=result.reason,
    )


def _return_on_average(
    lines: tuple[FinancialStatementLine, ...],
    key: str,
    name: str,
    numerator_account: _Account,
    base_account: _Account,
) -> IndicatorValue:
    numerator = _resolve(lines, numerator_account, AmountPeriod.CURRENT)
    opening = _resolve(lines, base_account, AmountPeriod.PRIOR)
    closing = _resolve(lines, base_account, AmountPeriod.CURRENT)
    average: Decimal | None = None
    if opening.spec.amount is not None and closing.spec.amount is not None:
        average = (opening.spec.amount + closing.spec.amount) / _TWO
    result = _finish((numerator, opening, closing), numerator.spec.amount, average)
    formula = (
        f"당기 {numerator_account.name} ÷ "
        f"((기초 {base_account.name} + 기말 {base_account.name}) ÷ 2) × 100"
    )
    return IndicatorValue(
        key=key,
        name=name,
        category=IndicatorCategory.PROFITABILITY,
        formula=formula,
        inputs=(numerator.spec, opening.spec, closing.spec),
        value=result.value,
        unavailable_reason=result.reason,
    )


def _figure(
    lines: tuple[FinancialStatementLine, ...],
    key: str,
    account: _Account,
) -> FinancialFigure:
    resolved = _resolve(lines, account, AmountPeriod.CURRENT)
    return FinancialFigure(
        key=key,
        name=account.name,
        sj_div=resolved.spec.sj_div,
        account_id=account.account_id,
        amount=resolved.spec.amount,
    )


def compute_annual_indicators(
    report: VersionedFinancialReport,
    lines: tuple[FinancialStatementLine, ...],
) -> AnnualIndicators:
    indicators = (
        _growth(lines, "revenue_growth", "매출액증가율", _REVENUE),
        _growth(lines, "operating_income_growth", "영업이익증가율", _OPERATING_INCOME),
        _growth(lines, "net_income_growth", "순이익증가율", _NET_INCOME),
        _ratio(
            lines,
            "operating_margin",
            "영업이익률",
            category=IndicatorCategory.PROFITABILITY,
            accounts=(_OPERATING_INCOME, _REVENUE),
        ),
        _ratio(
            lines,
            "net_margin",
            "순이익률",
            category=IndicatorCategory.PROFITABILITY,
            accounts=(_NET_INCOME, _REVENUE),
        ),
        _return_on_average(lines, "roe", "ROE(지배주주)", _NET_INCOME_OWNERS, _EQUITY_OWNERS),
        _return_on_average(lines, "roa", "ROA", _NET_INCOME, _ASSETS),
        _ratio(
            lines,
            "debt_ratio",
            "부채비율",
            category=IndicatorCategory.STABILITY,
            accounts=(_LIABILITIES, _EQUITY),
        ),
        _ratio(
            lines,
            "current_ratio",
            "유동비율",
            category=IndicatorCategory.STABILITY,
            accounts=(_CURRENT_ASSETS, _CURRENT_LIABILITIES),
        ),
    )
    figures = tuple(_figure(lines, key, account) for key, account in _FIGURES)
    return AnnualIndicators(
        bsns_year=report.bsns_year,
        reprt_code=report.reprt_code,
        fs_div=report.fs_div,
        rcept_no=report.rcept_no,
        currency=report.currency,
        version=report.version,
        figures=figures,
        indicators=indicators,
    )
