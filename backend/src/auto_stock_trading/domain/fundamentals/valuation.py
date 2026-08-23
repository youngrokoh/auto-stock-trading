from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.fundamentals.financial_statements import (
    StatementDivision,
    normalized_account_id,
)
from auto_stock_trading.domain.fundamentals.indicators import (
    AccountResolution,
    IndicatorUnavailableReason,
)
from auto_stock_trading.domain.market_data.share_classes import ShareClassKind  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialStatementLine,
        FsDivision,
        ReportCode,
        VersionedFinancialReport,
    )

_EPS_ACCOUNT_ID = "ifrs-full_BasicEarningsLossPerShare"
_EQUITY_OWNERS_ACCOUNT_ID = "ifrs-full_EquityAttributableToOwnersOfParent"
_KIS_SOURCE = "KIS"
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
    resolution: AccountResolution = AccountResolution.STANDARD_ACCOUNT


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
class ShareClassQuote:
    """상장 클래스 하나의 시세와 주식수. 우선주도 같은 TR로 조회된다.

    비유동 우선주는 당일 거래가 없어 전일 종가만 돌아온다(실측 `00088K`). 그래서 기준시각과
    거래량을 값과 함께 들고 다닌다.
    """

    symbol: str
    class_kind: ShareClassKind
    name: str
    price: Decimal | None
    as_of: datetime | None
    volume: int | None
    share_count: int | None
    share_count_as_of: datetime | None
    share_count_version: int = 1

    @property
    def market_cap(self) -> Decimal | None:
        if self.price is None or self.share_count is None:
            return None
        return self.price * self.share_count


@dataclass(frozen=True, slots=True)
class Valuation:
    price: PriceBasis | None
    share_count: ShareCountBasis | None
    report: ReportBasis
    items: tuple[ValuationItem, ...]
    # 상장 클래스 내역. 하나로 합쳐 놓으면 어느 클래스가 빠진 값인지 알 수 없다.
    share_classes: tuple[ShareClassQuote, ...] = ()


@dataclass(frozen=True, slots=True)
class _EpsFact:
    value: Decimal | None
    reason: IndicatorUnavailableReason | None
    resolution: AccountResolution = AccountResolution.STANDARD_ACCOUNT


# 손익 계정은 회사의 제출 형식에 따라 IS 또는 CIS에 실린다(지표 계약 §입력 계정).
_EPS_DIVISIONS: Final = (
    StatementDivision.INCOME_STATEMENT,
    StatementDivision.COMPREHENSIVE_INCOME,
)
_BALANCE_DIVISIONS: Final = (StatementDivision.BALANCE_SHEET,)


def basic_eps(
    lines: tuple[FinancialStatementLine, ...],
    *,
    preferred_listed: bool | None = None,
) -> Decimal | None:
    """공시 기본주당이익 원문. 가치지표와 종합 순위 전략이 같은 정의를 쓰게 한다.

    `preferred_listed=False`는 "상장된 우선주가 없음을 안다"는 뜻이며, 그때만 계정명 후보를
    쓴다(지표 계약 §우선주 반영). `None`은 모른다는 뜻이므로 복원하지 않는다.
    """
    return _resolve_eps(lines, preferred_listed=preferred_listed).value


def _resolve_eps(
    lines: tuple[FinancialStatementLine, ...],
    *,
    preferred_listed: bool | None = None,
) -> _EpsFact:
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
        return _restored_eps(lines, preferred_listed=preferred_listed)
    if continuing.amount is None:
        return _EpsFact(value=None, reason=continuing.reason)
    return _reconstructed_eps(lines, continuing.amount)


def _restored_eps(
    lines: tuple[FinancialStatementLine, ...],
    *,
    preferred_listed: bool | None,
) -> _EpsFact:
    named = _named_common_eps(lines, preferred_listed=preferred_listed)
    if named is None:
        return _EpsFact(value=None, reason=IndicatorUnavailableReason.MISSING_ACCOUNT)
    return _EpsFact(
        value=named,
        reason=None,
        resolution=AccountResolution.NO_PREFERRED_CLASS,
    )


def _reconstructed_eps(
    lines: tuple[FinancialStatementLine, ...],
    continuing: Decimal,
) -> _EpsFact:
    """중단영업 행이 원문에 아예 없으면 계속영업이 총액이다. 행은 있고 금액이 없으면 fail-closed."""
    discontinued = _single_amount(lines, _EPS_DISCONTINUED_ACCOUNT_ID)
    if not discontinued.present:
        return _EpsFact(value=continuing, reason=None)
    if discontinued.amount is None:
        return _EpsFact(value=None, reason=discontinued.reason)
    return _EpsFact(value=continuing + discontinued.amount, reason=None)


@dataclass(frozen=True, slots=True)
class _AccountAmount:
    present: bool
    amount: Decimal | None
    reason: IndicatorUnavailableReason | None


def _single_amount(
    lines: tuple[FinancialStatementLine, ...],
    account_id: str,
    *,
    divisions: tuple[StatementDivision, ...] = _EPS_DIVISIONS,
) -> _AccountAmount:
    """구분 우선순위(IS -> CIS)로 계정 한 행을 찾는다. 원문에 없으면 `present=False`다."""
    matches: list[FinancialStatementLine] = []
    for division in divisions:
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


_DILUTED_ONLY: Final = "희석"
_BASIC_AND_DILUTED: Final = "기본및희석"
_PER_SHARE_HINT: Final = "주당"
_PREFERRED_HINT: Final = "우선주"
_DISCONTINUED_HINT: Final = "중단"


def _named_common_eps(
    lines: tuple[FinancialStatementLine, ...],
    *,
    preferred_listed: bool | None,
) -> Decimal | None:
    """상장된 우선주가 없을 때만 계정명 후보를 쓴다(지표 계약 §우선주 반영).

    근거는 이름이 아니라 외부 사실이다 — 우선주가 상장되지 않은 회사의 주당이익 행은 우선주
    주당이익일 수 없다. 우선주가 있으면 두 클래스 EPS 차이가 실측 +219%~-76%까지 벌어져
    후보가 1행이어도 어느 클래스인지 증명할 수 없다.
    """
    if preferred_listed is not False:
        return None
    for division in _EPS_DIVISIONS:
        rows = [line for line in lines if line.sj_div is division]
        if not rows:
            continue
        candidates = [
            line.thstrm_amount
            for line in rows
            if line.account_id is None
            and _PER_SHARE_HINT in line.account_nm
            and _PREFERRED_HINT not in line.account_nm
            and _DISCONTINUED_HINT not in line.account_nm
            and _DILUTED_ONLY
            not in "".join(line.account_nm.split()).replace(_BASIC_AND_DILUTED, "기본")
            and line.thstrm_amount is not None
        ]
        return candidates[0] if len(candidates) == 1 else None
    return None


def _per_item(price: Decimal | None, eps: _EpsFact) -> ValuationItem:
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    if price is None:
        reason = IndicatorUnavailableReason.MISSING_QUOTE
    elif eps.reason is not None:
        reason = eps.reason
    elif eps.value == 0:
        reason = IndicatorUnavailableReason.ZERO_DENOMINATOR
    elif eps.value is not None:
        value = (price / eps.value).quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP)
    return ValuationItem(
        key="per",
        name="PER",
        unit="ratio",
        formula="보통주 현재가 ÷ 최근 연간 기본주당이익",
        value=value,
        unavailable_reason=reason,
    )


def _market_cap_item(common: ShareClassQuote | None) -> ValuationItem:
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    if common is None or common.price is None:
        reason = IndicatorUnavailableReason.MISSING_QUOTE
    elif common.share_count is None:
        reason = IndicatorUnavailableReason.MISSING_SHARE_COUNT
    else:
        value = common.price * common.share_count
    return ValuationItem(
        key="market_cap",
        name="시가총액(보통주)",
        unit="krw",
        formula="보통주 현재가 × 보통주 상장주식수",
        value=value,
        unavailable_reason=reason,
    )


def _unknown_total() -> ValuationItem:
    """상장 클래스 사실이 없으면 합계를 만들 수 없다. 보통주만 더한 값을 합계라 부르지 않는다."""
    return ValuationItem(
        key="market_cap_total",
        name="시가총액(전종목)",
        unit="krw",
        formula="Σ 클래스별 (현재가 × 상장주식수)",
        value=None,
        unavailable_reason=IndicatorUnavailableReason.MISSING_CLASS_QUOTE,
    )


def _market_cap_total_item(classes: Sequence[ShareClassQuote]) -> ValuationItem:
    """클래스가 하나라도 빠지면 값을 만들지 않는다.

    일부만 더한 합계는 틀린 값이고, 작아 보이는 값이 조용히 들어가는 것이 가장 나쁘다.
    """
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    if not classes:
        reason = IndicatorUnavailableReason.MISSING_QUOTE
    elif any(item.market_cap is None for item in classes):
        reason = IndicatorUnavailableReason.MISSING_CLASS_QUOTE
    else:
        total = Decimal(0)
        for item in classes:
            class_cap = item.market_cap
            if class_cap is not None:
                total += class_cap
        value = total
    return ValuationItem(
        key="market_cap_total",
        name="시가총액(전종목)",
        unit="krw",
        formula="Σ 클래스별 (현재가 × 상장주식수)",
        value=value,
        unavailable_reason=reason,
    )


def _bps_item(
    lines: tuple[FinancialStatementLine, ...],
    common: ShareClassQuote | None,
    *,
    preferred_listed: bool | None,
) -> ValuationItem:
    """우선주가 상장되지 않은 회사만 계산한다(지표 계약 §우선주 반영).

    그 경우 지배주주지분 전부가 보통주의 것이라 배분 판단이 필요 없다. 우선주가 있으면
    자본잉여금·이익잉여금 배분이 회계 판단이므로 자본금(par) 차감으로 대체하지 않는다.
    """
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    equity = _single_amount(lines, _EQUITY_OWNERS_ACCOUNT_ID, divisions=_BALANCE_DIVISIONS)
    if preferred_listed is None:
        reason = IndicatorUnavailableReason.MISSING_SHARE_COUNT
    elif preferred_listed:
        reason = IndicatorUnavailableReason.PREFERRED_ALLOCATION_REQUIRED
    elif common is None or common.share_count is None:
        reason = IndicatorUnavailableReason.MISSING_SHARE_COUNT
    elif not equity.present:
        reason = IndicatorUnavailableReason.MISSING_ACCOUNT
    elif equity.amount is None:
        reason = equity.reason
    elif common.share_count == 0:
        reason = IndicatorUnavailableReason.ZERO_DENOMINATOR
    else:
        value = (equity.amount / common.share_count).quantize(
            _RATIO_QUANTUM, rounding=ROUND_HALF_UP
        )
    return ValuationItem(
        key="bps",
        name="주당순자산(보통주)",
        unit="krw",
        formula="최근 연간 지배주주지분 ÷ 보통주 상장주식수",
        value=value,
        unavailable_reason=reason,
    )


def _pbr_item(common: ShareClassQuote | None, bps: ValuationItem) -> ValuationItem:
    value: Decimal | None = None
    reason: IndicatorUnavailableReason | None = None
    price = None if common is None else common.price
    if bps.unavailable_reason is not None:
        reason = bps.unavailable_reason
    elif price is None:
        reason = IndicatorUnavailableReason.MISSING_QUOTE
    elif bps.value is None or bps.value == 0:
        reason = IndicatorUnavailableReason.ZERO_DENOMINATOR
    else:
        value = (price / bps.value).quantize(_RATIO_QUANTUM, rounding=ROUND_HALF_UP)
    return ValuationItem(
        key="pbr",
        name="PBR",
        unit="ratio",
        formula="보통주 현재가 ÷ 주당순자산(보통주)",
        value=value,
        unavailable_reason=reason,
    )


def compute_valuation(
    report: VersionedFinancialReport,
    lines: tuple[FinancialStatementLine, ...],
    common: ShareClassQuote | None,
    preferred: Sequence[ShareClassQuote] | None,
) -> Valuation:
    """가치지표.

    `preferred`가 `None`이면 **상장 클래스 사실을 모른다**는 뜻이고, 빈 목록이면 **우선주가 없음을
    안다**는 뜻이다. 둘을 같은 값으로 두면 사실이 아직 수집되지 않은 상태에서 우선주가 없다고
    단정하게 된다. 모르는 상태에서는 EPS 복원과 BPS를 하지 않는다.
    """
    classes = () if common is None else (common, *(preferred if preferred is not None else ()))
    preferred_listed = None if preferred is None else len(preferred) > 0
    eps = _resolve_eps(lines, preferred_listed=preferred_listed)
    eps_item = ValuationItem(
        key="eps",
        name="기본주당이익",
        unit="krw",
        formula="최근 연간 보고서의 기본주당이익 원문 값",
        value=eps.value,
        unavailable_reason=eps.reason,
        resolution=eps.resolution,
    )
    price = (
        None
        if common is None or common.price is None or common.as_of is None
        else PriceBasis(price=common.price, as_of=common.as_of, source=_KIS_SOURCE)
    )
    share_basis = (
        None
        if common is None or common.share_count is None or common.share_count_as_of is None
        else ShareCountBasis(
            share_count=common.share_count,
            as_of=common.share_count_as_of,
            source=_KIS_SOURCE,
            version=common.share_count_version,
        )
    )
    bps = _bps_item(lines, common, preferred_listed=preferred_listed)
    total = _unknown_total() if preferred is None else _market_cap_total_item(classes)
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
        items=(
            eps_item,
            _per_item(None if common is None else common.price, eps),
            _market_cap_item(common),
            total,
            bps,
            _pbr_item(common, bps),
        ),
        share_classes=classes,
    )
