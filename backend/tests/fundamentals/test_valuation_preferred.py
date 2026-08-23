"""우선주 반영 가치지표(지표 계약 §우선주 반영, 2026-08-23 승인).

우선주를 모르면 시가총액이 보통주분만 잡히고 BPS가 어느 클래스의 것인지 확정되지 않는다.
여기서 고정하는 것은 세 가지다: 클래스 합계는 하나라도 빠지면 만들지 않는다, BPS는 우선주가
있으면 계산하지 않는다, EPS 복원은 우선주가 없는 회사만 허용한다.
"""

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
    IndicatorUnavailableReason,
)
from auto_stock_trading.domain.fundamentals.valuation import (
    ShareClassQuote,
    Valuation,
    ValuationItem,
    compute_valuation,
)
from auto_stock_trading.domain.market_data.share_classes import ShareClassKind

_NOW = datetime(2026, 8, 23, 4, 39, tzinfo=UTC)
_STALE = datetime(2026, 8, 22, 6, 30, tzinfo=UTC)


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
    amount: str | None,
) -> FinancialStatementLine:
    return FinancialStatementLine(
        line_seq=line_seq,
        sj_div=sj_div,
        account_id=account_id,
        account_nm=account_nm,
        account_detail=None,
        ord=line_seq,
        thstrm_nm="제 57 기",
        thstrm_amount=None if amount is None else Decimal(amount),
        frmtrm_nm="제 56 기",
        frmtrm_amount=None,
        bfefrmtrm_nm=None,
        bfefrmtrm_amount=None,
    )


def _lines(
    *, eps_account: str | None = "ifrs-full_BasicEarningsLossPerShare"
) -> tuple[FinancialStatementLine, ...]:
    bs = StatementDivision.BALANCE_SHEET
    cis = StatementDivision.COMPREHENSIVE_INCOME
    return (
        _line(1, bs, "ifrs-full_EquityAttributableToOwnersOfParent", "지배기업 소유주지분", "2000"),
        _line(
            2,
            cis,
            eps_account,
            "기본주당이익" if eps_account is not None else "보통주 기본주당이익",
            "100",
        ),
    )


def _class_quote(  # noqa: PLR0913
    symbol: str,
    kind: ShareClassKind,
    price: str,
    share_count: int,
    *,
    as_of: datetime = _NOW,
    volume: int = 1000,
) -> ShareClassQuote:
    return ShareClassQuote(
        symbol=symbol,
        class_kind=kind,
        name=f"{symbol} 종목명",
        price=Decimal(price),
        as_of=as_of,
        volume=volume,
        share_count=share_count,
        share_count_as_of=as_of,
    )


_COMMON = _class_quote("005930", ShareClassKind.COMMON, "281500", 5_846_278_608)
_PREFERRED = _class_quote("005935", ShareClassKind.PREFERRED, "207000", 802_371_203)


def _items(valuation: Valuation) -> dict[str, ValuationItem]:
    return {item.key: item for item in valuation.items}


def test_the_total_market_cap_sums_every_listed_class() -> None:
    """실측: 보통주만 세면 삼성전자 시가총액이 실제의 90.8%다."""
    valuation = compute_valuation(_report(), _lines(), _COMMON, (_PREFERRED,))

    items = _items(valuation)
    assert items["market_cap"].value == Decimal(281500) * 5_846_278_608
    assert items["market_cap_total"].value == Decimal(1_811_818_267_173_000)
    assert [entry.symbol for entry in valuation.share_classes] == ["005930", "005935"]
    assert valuation.share_classes[1].market_cap == Decimal(207000) * 802_371_203


def test_a_company_without_preferred_shares_has_equal_totals() -> None:
    valuation = compute_valuation(_report(), _lines(), _COMMON, ())

    items = _items(valuation)
    assert items["market_cap"].value == items["market_cap_total"].value


def test_a_missing_class_quote_refuses_the_total_but_keeps_the_common() -> None:
    """일부만 더한 합계는 틀린 값이다. 작아 보이는 값이 조용히 들어가는 것이 가장 나쁘다."""
    incomplete = ShareClassQuote(
        symbol="005935",
        class_kind=ShareClassKind.PREFERRED,
        name="삼성전자우",
        price=None,
        as_of=None,
        volume=None,
        share_count=802_371_203,
        share_count_as_of=_NOW,
    )

    valuation = compute_valuation(_report(), _lines(), _COMMON, (incomplete,))

    items = _items(valuation)
    assert items["market_cap"].value == Decimal(281500) * 5_846_278_608
    assert items["market_cap_total"].value is None
    assert (
        items["market_cap_total"].unavailable_reason
        is IndicatorUnavailableReason.MISSING_CLASS_QUOTE
    )


def test_a_stale_preferred_price_is_kept_but_its_as_of_is_exposed() -> None:
    """실측: 비유동 우선주는 거래가 없어 전일 종가만 돌아온다(`00088K`)."""
    stale = _class_quote(
        "00088K",
        ShareClassKind.PREFERRED,
        "29250",
        19_404_441,
        as_of=_STALE,
        volume=0,
    )

    valuation = compute_valuation(_report(), _lines(), _COMMON, (stale,))

    entry = valuation.share_classes[1]
    assert entry.as_of == _STALE
    assert entry.volume == 0
    assert _items(valuation)["market_cap_total"].value is not None


def test_bps_rounding_to_zero_fails_the_pbr_closed() -> None:
    """지배주주지분 2000원을 58억주로 나누면 0.00이 된다. 0으로 나누지 않는다."""
    valuation = compute_valuation(_report(), _lines(), _COMMON, ())

    items = _items(valuation)
    assert items["bps"].value == Decimal("0.00")
    assert items["pbr"].value is None
    assert items["pbr"].unavailable_reason is IndicatorUnavailableReason.ZERO_DENOMINATOR


def test_bps_uses_the_owners_equity_over_the_common_share_count() -> None:
    common = _class_quote("005930", ShareClassKind.COMMON, "1000", 4)
    lines = (
        _line(
            1,
            StatementDivision.BALANCE_SHEET,
            "ifrs-full_EquityAttributableToOwnersOfParent",
            "지배기업 소유주지분",
            "8000",
        ),
        _line(
            2,
            StatementDivision.COMPREHENSIVE_INCOME,
            "ifrs-full_BasicEarningsLossPerShare",
            "기본주당이익",
            "100",
        ),
    )

    valuation = compute_valuation(_report(), lines, common, ())

    items = _items(valuation)
    assert items["bps"].value == Decimal("2000.00")
    assert items["pbr"].value == Decimal("0.50")


def test_bps_is_refused_when_a_preferred_class_is_listed() -> None:
    """자본잉여금·이익잉여금 배분은 회계 판단이다. 자본금 차감으로 대체하지 않는다."""
    valuation = compute_valuation(_report(), _lines(), _COMMON, (_PREFERRED,))

    items = _items(valuation)
    assert items["bps"].value is None
    assert (
        items["bps"].unavailable_reason is IndicatorUnavailableReason.PREFERRED_ALLOCATION_REQUIRED
    )
    assert (
        items["pbr"].unavailable_reason is IndicatorUnavailableReason.PREFERRED_ALLOCATION_REQUIRED
    )


def test_a_name_only_eps_is_restored_when_no_preferred_class_is_listed() -> None:
    """우선주가 없으면 그 행이 우선주 주당이익일 수 없다. 외부 사실이 근거다."""
    valuation = compute_valuation(_report(), _lines(eps_account=None), _COMMON, ())

    items = _items(valuation)
    assert items["eps"].value == Decimal(100)
    assert items["eps"].resolution is AccountResolution.NO_PREFERRED_CLASS
    assert items["per"].value is not None


def test_a_name_only_eps_is_refused_when_a_preferred_class_is_listed() -> None:
    """두 클래스 EPS 차이가 실측 +219%~-76%다. 후보가 1행이어도 증명할 수 없다."""
    valuation = compute_valuation(_report(), _lines(eps_account=None), _COMMON, (_PREFERRED,))

    items = _items(valuation)
    assert items["eps"].value is None
    assert items["eps"].unavailable_reason is IndicatorUnavailableReason.MISSING_ACCOUNT


def test_a_name_only_eps_is_refused_without_share_class_facts() -> None:
    """클래스 사실이 없으면 우선주 유무를 모른다. 모르면 복원하지 않는다."""
    valuation = compute_valuation(_report(), _lines(eps_account=None), _COMMON, None)

    items = _items(valuation)
    assert items["eps"].value is None
    assert items["eps"].unavailable_reason is IndicatorUnavailableReason.MISSING_ACCOUNT


def test_two_name_only_eps_candidates_are_refused() -> None:
    lines = (
        *_lines(eps_account=None),
        _line(
            3,
            StatementDivision.COMPREHENSIVE_INCOME,
            None,
            "보통주기본주당순이익",
            "120",
        ),
    )

    valuation = compute_valuation(_report(), lines, _COMMON, ())

    assert _items(valuation)["eps"].value is None


def test_a_standard_tagged_eps_reports_the_standard_resolution() -> None:
    valuation = compute_valuation(_report(), _lines(), _COMMON, ())

    assert _items(valuation)["eps"].resolution is AccountResolution.STANDARD_ACCOUNT
