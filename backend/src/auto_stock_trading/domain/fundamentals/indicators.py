from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.fundamentals.financial_statements import (
    StatementDivision,
    normalized_account_id,
)

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
    # 발행사가 업종 특성상 매출액·영업이익 표준계정을 쓰지 않는다(계정 누락과 구별한다).
    SECTOR_ACCOUNT_BASIS = "SECTOR_ACCOUNT_BASIS"
    # 상장 클래스 중 시세·주식수가 빠져 전종목 합계를 만들 수 없다.
    MISSING_CLASS_QUOTE = "MISSING_CLASS_QUOTE"
    # 우선주가 상장돼 자본 배분 판단이 필요하다(데이터 결손과 구별한다).
    PREFERRED_ALLOCATION_REQUIRED = "PREFERRED_ALLOCATION_REQUIRED"


class AmountPeriod(StrEnum):
    CURRENT = "thstrm"
    PRIOR = "frmtrm"


class AccountResolution(StrEnum):
    """금액을 어떻게 얻었는지(지표 계약 §표준계정 결측 시 복원 규칙).

    복원한 값과 표준 태깅된 값이 응답에서 구별되지 않으면 안 된다.
    """

    STANDARD_ACCOUNT = "standard_account"
    IDENTITY_VERIFIED = "identity_verified"
    STANDARD_DIFFERENCE = "standard_difference"
    # 상장된 우선주가 없다는 외부 사실로 계정명 후보를 확정했다(지표 계약 §우선주 반영).
    NO_PREFERRED_CLASS = "no_preferred_class"


@dataclass(frozen=True, slots=True)
class IndicatorInput:
    name: str
    sj_div: StatementDivision
    account_id: str
    period: AmountPeriod
    amount: Decimal | None
    resolution: AccountResolution = AccountResolution.STANDARD_ACCOUNT


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
    resolution: AccountResolution = AccountResolution.STANDARD_ACCOUNT


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
_NONCONTROLLING_EQUITY = _Account(
    "비지배지분",
    _BALANCE_DIVISIONS,
    "ifrs-full_NoncontrollingInterests",
)


@dataclass(frozen=True, slots=True)
class _Decomposition:
    """분해 항등식 `합계 = 이 계정 + 보완 계정`. 계정명은 후보를 좁히는 데만 쓴다."""

    total: _Account
    name_hints: tuple[str, ...]
    exclude_hints: tuple[str, ...]
    complement_hints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Difference:
    """표준계정 두 개의 차. 이름을 전혀 쓰지 않는다."""

    minuend: _Account
    subtrahend: _Account


# '비지배주주지분포괄손익'처럼 보완 항목의 이름이 '지배주주'를 포함하므로 제외 힌트가 필요하다.
_DECOMPOSITIONS: Final = {
    _NET_INCOME_OWNERS.account_id: _Decomposition(
        total=_NET_INCOME,
        name_hints=("지배기업", "지배주주"),
        exclude_hints=("비지배",),
        complement_hints=("비지배",),
    ),
}
_DIFFERENCES: Final = {
    _EQUITY_OWNERS.account_id: _Difference(
        minuend=_EQUITY,
        subtrahend=_NONCONTROLLING_EQUITY,
    ),
}

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
    resolution = AccountResolution.STANDARD_ACCOUNT
    if len(matches) > 1:
        reason = IndicatorUnavailableReason.AMBIGUOUS_ACCOUNT
    elif matches:
        amount = _amount(matches[0], period)
        if amount is None:
            # 원문이 그 계정에 대해 말을 했고 값이 없다. 다른 경로로 값을 만들지 않는다.
            reason = IndicatorUnavailableReason.MISSING_AMOUNT
    else:
        restored = _restored(lines, account, period)
        if restored is None:
            reason = IndicatorUnavailableReason.MISSING_ACCOUNT
        else:
            division = restored.division
            amount = restored.amount
            resolution = restored.resolution
    spec = IndicatorInput(
        name=account.name,
        sj_div=division,
        account_id=account.account_id,
        period=period,
        amount=amount,
        resolution=resolution,
    )
    return _ResolvedInput(spec=spec, reason=reason)


def _amount(line: FinancialStatementLine, period: AmountPeriod) -> Decimal | None:
    return line.thstrm_amount if period is AmountPeriod.CURRENT else line.frmtrm_amount


@dataclass(frozen=True, slots=True)
class _Restored:
    amount: Decimal
    division: StatementDivision
    resolution: AccountResolution


def _restored(
    lines: tuple[FinancialStatementLine, ...],
    account: _Account,
    period: AmountPeriod,
) -> _Restored | None:
    """표준계정이 아예 없을 때만 산술로 복원한다(지표 계약 §표준계정 결측 시 복원 규칙)."""
    difference = _DIFFERENCES.get(account.account_id)
    if difference is not None:
        return _by_difference(lines, difference, period)
    decomposition = _DECOMPOSITIONS.get(account.account_id)
    if decomposition is not None:
        return _by_identity(lines, decomposition, period)
    return None


def _single_standard_amount(
    lines: tuple[FinancialStatementLine, ...],
    account: _Account,
    period: AmountPeriod,
) -> tuple[StatementDivision, Decimal] | None:
    division, matches = _matching_lines(lines, account)
    if len(matches) != 1:
        return None
    amount = _amount(matches[0], period)
    return None if amount is None else (division, amount)


def _by_difference(
    lines: tuple[FinancialStatementLine, ...],
    spec: _Difference,
    period: AmountPeriod,
) -> _Restored | None:
    minuend = _single_standard_amount(lines, spec.minuend, period)
    subtrahend = _single_standard_amount(lines, spec.subtrahend, period)
    if minuend is None or subtrahend is None:
        return None
    division, minuend_amount = minuend
    return _Restored(
        amount=minuend_amount - subtrahend[1],
        division=division,
        resolution=AccountResolution.STANDARD_DIFFERENCE,
    )


def _hits(account_nm: str, hints: tuple[str, ...]) -> bool:
    squeezed = "".join(account_nm.split())
    return any(hint in squeezed for hint in hints)


def _by_identity(
    lines: tuple[FinancialStatementLine, ...],
    spec: _Decomposition,
    period: AmountPeriod,
) -> _Restored | None:
    """항등식을 만족하는 금액이 유일할 때만 채택한다. 값을 결정하는 것은 이름이 아니라 산술이다."""
    total = _single_standard_amount(lines, spec.total, period)
    if total is None:
        return None
    division, total_amount = total
    rows = [line for line in lines if line.sj_div is division]
    candidates = [
        (line, amount)
        for line in rows
        # 표준 ID가 있는 행은 이미 다른 계정이다. 다른 의미의 표준계정을 이름으로 끌어오지 않는다.
        if line.account_id is None
        and _hits(line.account_nm, spec.name_hints)
        and not _hits(line.account_nm, spec.exclude_hints)
        and (amount := _amount(line, period)) is not None
    ]
    complements = [
        amount
        for line in rows
        if _hits(line.account_nm, spec.complement_hints)
        and (amount := _amount(line, period)) is not None
    ]
    resolved = {
        amount
        for _, amount in candidates
        if any(amount + complement == total_amount for complement in complements)
    }
    if len(resolved) != 1:
        return None
    return _Restored(
        amount=next(iter(resolved)),
        division=division,
        resolution=AccountResolution.IDENTITY_VERIFIED,
    )


def _matching_lines(
    lines: tuple[FinancialStatementLine, ...],
    account: _Account,
) -> tuple[StatementDivision, list[FinancialStatementLine]]:
    """실제로 사용한 구분과 그 안의 후보 행을 돌려준다. 모호성은 사용한 구분 안에서만 본다."""
    for division in account.divisions:
        matches = [
            line
            for line in lines
            if line.sj_div is division
            and normalized_account_id(line.account_id) == account.account_id
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
        resolution=resolved.spec.resolution,
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


_OPERATING_ACCOUNT_IDS: Final = frozenset({_REVENUE.account_id, _OPERATING_INCOME.account_id})


def relabel_operating_account_basis(annual: AnnualIndicators) -> AnnualIndicators:
    """매출액·영업이익 계정이 없어 실패한 지표의 사유를 업종 기준으로 다시 표기한다.

    값은 만들지 않는다. 계정이 없는 사실은 그대로이고, 그 원인이 발행사의 업종 회계라는 것만
    분명히 한다. 금액 결측·모호 같은 다른 실패는 업종 문제가 아니므로 건드리지 않는다.
    """
    return replace(
        annual,
        indicators=tuple(_relabelled(item) for item in annual.indicators),
    )


def _relabelled(item: IndicatorValue) -> IndicatorValue:
    if item.unavailable_reason is not IndicatorUnavailableReason.MISSING_ACCOUNT:
        return item
    if not any(spec.account_id in _OPERATING_ACCOUNT_IDS for spec in item.inputs):
        return item
    return replace(item, unavailable_reason=IndicatorUnavailableReason.SECTOR_ACCOUNT_BASIS)
