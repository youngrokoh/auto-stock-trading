from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.fundamentals.financial_statements import (
    StatementDivision,
    normalized_account_id,
)
from auto_stock_trading.domain.fundamentals.indicators import IndicatorUnavailableReason

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialStatementLine,
        FsDivision,
        ReportCode,
        VersionedFinancialReport,
    )
    from auto_stock_trading.domain.market_data.listed_shares import VersionedListedShareCount
    from auto_stock_trading.domain.market_data.models import Quote

_EPS_ACCOUNT_ID = "ifrs-full_BasicEarningsLossPerShare"
# 총 기본주당이익 대신 계속·중단영업으로 나눠 표시하는 회사가 있다(실측 14종목).
_EPS_CONTINUING_ACCOUNT_ID = "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"
_EPS_DISCONTINUED_ACCOUNT_ID = "ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations"
_RATIO_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ValuationItem:
    key: str
    name: str
    unit: str
    formula: str
    value: Decimal | None
    unavailable_reason: IndicatorUnavailableReason | None


@dataclass(frozen=True, slots=True)
class PriceBasis:
    price: Decimal
    as_of: datetime
    source: str


@dataclass(frozen=True, slots=True)
class ShareCountBasis:
    share_count: int
    as_of: datetime
    source: str
    version: int


@dataclass(frozen=True, slots=True)
class ReportBasis:
    bsns_year: int
    reprt_code: ReportCode
    fs_div: FsDivision
    rcept_no: str
    version: int


@dataclass(frozen=True, slots=True)
class Valuation:
    price: PriceBasis | None
    share_count: ShareCountBasis | None
    report: ReportBasis
    items: tuple[ValuationItem, ...]


@dataclass(frozen=True, slots=True)
class _EpsFact:
    value: Decimal | None
    reason: IndicatorUnavailableReason | None


# 손익 계정은 회사의 제출 형식에 따라 IS 또는 CIS에 실린다(지표 계약 §입력 계정).
_EPS_DIVISIONS: Final = (
    StatementDivision.INCOME_STATEMENT,
    StatementDivision.COMPREHENSIVE_INCOME,
)


def basic_eps(lines: tuple[FinancialStatementLine, ...]) -> Decimal | None:
    """공시 기본주당이익 원문. 가치지표와 종합 순위 전략이 같은 정의를 쓰게 한다."""
    return _resolve_eps(lines).value


def _resolve_eps(lines: tuple[FinancialStatementLine, ...]) -> _EpsFact:
    """총 기본주당이익. 없으면 계속영업 + 중단영업으로 복원한다(지표 계약 §가치지표).

    복원은 같은 주당이익 체계 안의 합이라 순이익 ÷ 주식수 같은 파생이 아니다. 중단영업 행이
    원문에 아예 없으면 중단영업이 없다는 뜻이라 계속영업이 총액이고, 행은 있는데 금액이 비어
    있으면 0으로 가정하지 않고 fail-closed다(둘 다 실측 사례가 있다).
    """
    total = _single_amount(lines, _EPS_ACCOUNT_ID)
    if total.present:
        return _EpsFact(value=total.amount, reason=total.reason)
    continuing = _single_amount(lines, _EPS_CONTINUING_ACCOUNT_ID)
    if not continuing.present:
        return _EpsFact(value=None, reason=IndicatorUnavailableReason.MISSING_ACCOUNT)
    if continuing.amount is None:
        return _EpsFact(value=None, reason=continuing.reason)
    discontinued = _single_amount(lines, _EPS_DISCONTINUED_ACCOUNT_ID)
    if not discontinued.present:
        return _EpsFact(value=continuing.amount, reason=None)
    if discontinued.amount is None:
        return _EpsFact(value=None, reason=discontinued.reason)
    return _EpsFact(value=continuing.amount + discontinued.amount, reason=None)


@dataclass(frozen=True, slots=True)
class _AccountAmount:
    present: bool
    amount: Decimal | None
    reason: IndicatorUnavailableReason | None


def _single_amount(
    lines: tuple[FinancialStatementLine, ...],
    account_id: str,
) -> _AccountAmount:
    """구분 우선순위(IS -> CIS)로 계정 한 행을 찾는다. 원문에 없으면 `present=False`다."""
    matches: list[FinancialStatementLine] = []
    for division in _EPS_DIVISIONS:
        matches = [
            line
            for line in lines
            if line.sj_div is division and normalized_account_id(line.account_id) == account_id
        ]
        if matches:
            break
    if not matches:
        return _AccountAmount(present=False, amount=None, reason=None)
    if len(matches) > 1:
        return _AccountAmount(
            present=True,
            amount=None,
            reason=IndicatorUnavailableReason.AMBIGUOUS_ACCOUNT,
        )
    amount = matches[0].thstrm_amount
    if amount is None:
        return _AccountAmount(
            present=True,
            amount=None,
            reason=IndicatorUnavailableReason.MISSING_AMOUNT,
        )
    return _AccountAmount(present=True, amount=amount, reason=None)


def _per_item(quote: Quote | None, eps: _EpsFact) -> ValuationItem:
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    if quote is None:
        reason = IndicatorUnavailableReason.MISSING_QUOTE
    elif eps.reason is not None:
        reason = eps.reason
    elif eps.value == 0:
        reason = IndicatorUnavailableReason.ZERO_DENOMINATOR
    elif eps.value is not None:
        value = (quote.price / eps.value).quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP)
    return ValuationItem(
        key="per",
        name="PER",
        unit="ratio",
        formula="현재가 ÷ 최근 연간 기본주당이익",
        value=value,
        unavailable_reason=reason,
    )


def _market_cap_item(
    quote: Quote | None,
    shares: VersionedListedShareCount | None,
) -> ValuationItem:
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    if quote is None:
        reason = IndicatorUnavailableReason.MISSING_QUOTE
    elif shares is None:
        reason = IndicatorUnavailableReason.MISSING_SHARE_COUNT
    else:
        value = quote.price * shares.share_count
    return ValuationItem(
        key="market_cap",
        name="시가총액(보통주)",
        unit="krw",
        formula="현재가 × 보통주 상장주식수",
        value=value,
        unavailable_reason=reason,
    )


def compute_valuation(
    report: VersionedFinancialReport,
    lines: tuple[FinancialStatementLine, ...],
    quote: Quote | None,
    shares: VersionedListedShareCount | None,
) -> Valuation:
    eps = _resolve_eps(lines)
    eps_item = ValuationItem(
        key="eps",
        name="기본주당이익",
        unit="krw",
        formula="최근 연간 보고서의 기본주당이익 원문 값",
        value=eps.value,
        unavailable_reason=eps.reason,
    )
    price = (
        None
        if quote is None
        else PriceBasis(price=quote.price, as_of=quote.as_of, source=quote.source)
    )
    share_basis = (
        None
        if shares is None
        else ShareCountBasis(
            share_count=shares.share_count,
            as_of=shares.as_of,
            source=shares.source,
            version=shares.version,
        )
    )
    return Valuation(
        price=price,
        share_count=share_basis,
        report=ReportBasis(
            bsns_year=report.bsns_year,
            reprt_code=report.reprt_code,
            fs_div=report.fs_div,
            rcept_no=report.rcept_no,
            version=report.version,
        ),
        items=(eps_item, _per_item(quote, eps), _market_cap_item(quote, shares)),
    )
