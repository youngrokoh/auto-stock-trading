"""가치·수익성·모멘텀 종합 순위(백테스트 계약 v3).

가장 위험한 부분은 시점 정합이다. 접수일 판정이 하루라도 느슨하면 백테스트가 그날 몰랐던
재무 정보를 쓰게 되고, 성과는 좋아지지만 전략은 거짓이 된다. 그래서 경계일을 고정한다.
"""

from datetime import date
from decimal import Decimal

import pytest

from auto_stock_trading.domain.strategies.composite_rank import (
    AnnualFact,
    CompositeParameters,
    SymbolFundamentals,
    composite_rebalances,
    disclosure_filed_on,
    point_in_time_fact,
)
from auto_stock_trading.domain.strategies.ranking import SymbolSeries

_TRADING_DATES = (
    date(2025, 3, 3),
    date(2025, 3, 4),
    date(2025, 3, 5),
    date(2025, 3, 6),
    date(2025, 3, 7),
)


def _fact(
    bsns_year: int,
    rcept_no: str,
    *,
    roe: str | None = "10",
    eps: str | None = "1000",
) -> AnnualFact:
    return AnnualFact(
        bsns_year=bsns_year,
        reprt_code="11011",
        fs_div="CFS",
        rcept_no=rcept_no,
        filed_on=disclosure_filed_on(rcept_no),
        roe=None if roe is None else Decimal(roe),
        eps=None if eps is None else Decimal(eps),
    )


def test_receipt_number_prefix_is_the_filing_date() -> None:
    assert disclosure_filed_on("20260317000635") == date(2026, 3, 17)


def test_a_malformed_receipt_number_is_rejected_instead_of_guessed() -> None:
    with pytest.raises(ValueError, match="receipt number"):
        _ = disclosure_filed_on("2026031")


def test_a_report_filed_on_the_signal_date_is_not_yet_usable() -> None:
    facts = (_fact(2024, "20250305000001"),)

    assert point_in_time_fact(facts, date(2025, 3, 5)) is None
    assert point_in_time_fact(facts, date(2025, 3, 6)) is not None


def test_the_latest_usable_business_year_wins() -> None:
    facts = (_fact(2023, "20240301000001"), _fact(2024, "20250306000001"))

    early = point_in_time_fact(facts, date(2025, 3, 5))
    later = point_in_time_fact(facts, date(2025, 3, 7))

    assert early is not None
    assert early.bsns_year == 2023
    assert later is not None
    assert later.bsns_year == 2024


def test_the_latest_known_correction_wins_within_a_business_year() -> None:
    facts = (_fact(2024, "20250306000001"), _fact(2024, "20250401000009"))

    before = point_in_time_fact(facts, date(2025, 3, 7))
    after = point_in_time_fact(facts, date(2025, 4, 2))

    assert before is not None
    assert before.rcept_no == "20250306000001"
    assert after is not None
    assert after.rcept_no == "20250401000009"


def _series(symbol: str, closes: dict[date, str]) -> SymbolSeries:
    return SymbolSeries(
        symbol=symbol,
        closes={day: Decimal(value) for day, value in closes.items()},
    )


def _flat_series(symbol: str, first: str, last: str) -> SymbolSeries:
    return _series(
        symbol,
        {
            date(2025, 3, 3): first,
            date(2025, 3, 4): first,
            date(2025, 3, 5): first,
            date(2025, 3, 6): first,
            date(2025, 3, 7): last,
        },
    )


_PARAMETERS = CompositeParameters(lookback_days=4, holdings=2)


def test_composite_rank_averages_the_three_factor_ranks() -> None:
    universe = (
        # 모멘텀 1위, 이익수익률 3위(1000/2000), ROE 3위 -> 평균 (1+3+3)/3 = 2.33
        _flat_series("000100", "1000", "2000"),
        # 모멘텀 3위, 이익수익률 1위(1000/500), ROE 1위 -> 평균 1.67
        _flat_series("000200", "1000", "500"),
        # 모멘텀 2위, 이익수익률 2위(1000/1000), ROE 2위 -> 평균 2.00
        _flat_series("000300", "1000", "1000"),
    )
    fundamentals = (
        SymbolFundamentals("000100", (_fact(2024, "20250101000001", roe="5"),)),
        SymbolFundamentals("000200", (_fact(2024, "20250101000002", roe="20"),)),
        SymbolFundamentals("000300", (_fact(2024, "20250101000003", roe="10"),)),
    )

    result = composite_rebalances(
        (date(2025, 3, 7),),
        universe,
        fundamentals,
        _PARAMETERS,
        _TRADING_DATES,
    )

    assert len(result.rebalances) == 1
    selected = result.rebalances[0].selected
    assert [item.symbol for item in selected] == ["000200", "000300"]
    assert selected[0].score == Decimal("1.6667")
    assert selected[1].score == Decimal("2.0000")


def test_tied_factor_values_share_the_average_rank() -> None:
    universe = (
        _flat_series("000100", "1000", "1000"),
        _flat_series("000200", "1000", "1000"),
    )
    fundamentals = (
        SymbolFundamentals("000100", (_fact(2024, "20250101000001", roe="10"),)),
        SymbolFundamentals("000200", (_fact(2024, "20250101000002", roe="10"),)),
    )

    result = composite_rebalances(
        (date(2025, 3, 7),),
        universe,
        fundamentals,
        _PARAMETERS,
        _TRADING_DATES,
    )

    scores = {item.symbol: item.score for item in result.rebalances[0].selected}
    # 세 요인이 모두 동점이면 두 종목의 평균 순위는 같아야 한다((1+2)/2 = 1.5).
    assert scores == {"000100": Decimal("1.5000"), "000200": Decimal("1.5000")}


def test_a_symbol_missing_one_factor_is_excluded_from_the_round() -> None:
    universe = (
        _flat_series("000100", "1000", "1000"),
        _flat_series("000200", "1000", "1000"),
        _flat_series("000300", "1000", "1000"),
    )
    fundamentals = (
        SymbolFundamentals("000100", (_fact(2024, "20250101000001"),)),
        # ROE 없음 -> 후보 아님
        SymbolFundamentals("000200", (_fact(2024, "20250101000002", roe=None),)),
        # 보고서가 아직 접수되지 않음 -> 후보 아님
        SymbolFundamentals("000300", (_fact(2024, "20260101000003"),)),
    )

    result = composite_rebalances(
        (date(2025, 3, 7),),
        universe,
        fundamentals,
        CompositeParameters(lookback_days=4, holdings=10),
        _TRADING_DATES,
    )

    assert [item.symbol for item in result.rebalances[0].selected] == ["000100"]


def test_a_round_without_candidates_is_not_created() -> None:
    universe = (_flat_series("000100", "1000", "1000"),)
    fundamentals = (SymbolFundamentals("000100", (_fact(2024, "20260101000001"),)),)

    result = composite_rebalances(
        (date(2025, 3, 7),),
        universe,
        fundamentals,
        _PARAMETERS,
        _TRADING_DATES,
    )

    assert result.rebalances == ()
    assert result.used_reports == ()


def test_used_reports_record_every_report_that_shaped_the_ranking() -> None:
    universe = (
        _flat_series("000100", "1000", "1000"),
        _flat_series("000200", "1000", "1000"),
    )
    fundamentals = (
        SymbolFundamentals("000100", (_fact(2024, "20250101000001"),)),
        SymbolFundamentals("000200", (_fact(2024, "20250101000002"),)),
    )

    result = composite_rebalances(
        (date(2025, 3, 7),),
        universe,
        fundamentals,
        CompositeParameters(lookback_days=4, holdings=1),
        _TRADING_DATES,
    )

    # 선정되지 않은 종목의 보고서도 순위를 결정했으므로 계보에 남는다.
    assert [(item.symbol, item.rcept_no) for item in result.used_reports] == [
        ("000100", "20250101000001"),
        ("000200", "20250101000002"),
    ]


def test_a_round_without_a_full_lookback_window_is_skipped() -> None:
    universe = (_flat_series("000100", "1000", "1000"),)
    fundamentals = (SymbolFundamentals("000100", (_fact(2024, "20250101000001"),)),)

    result = composite_rebalances(
        (date(2025, 3, 4),),
        universe,
        fundamentals,
        CompositeParameters(lookback_days=4, holdings=1),
        _TRADING_DATES,
    )

    assert result.rebalances == ()
