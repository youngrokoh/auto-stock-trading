"""재무 특징과 특징 집합 버전(ML 신호 계약 §특징).

재무는 연 1회 갱신되고 접수일 이후에만 알 수 있다. 가격 특징과 같은 규칙을 지켜야 한다:
없으면 채우지 않고 그 종목-일 표본을 만들지 않는다.
"""

from datetime import date
from decimal import Decimal

import pytest

from auto_stock_trading.domain.strategies.composite_rank import (
    AnnualFact,
    disclosure_filed_on,
)
from auto_stock_trading.features.feature_set import (
    FEATURE_SET_PRICE,
    FEATURE_SET_WITH_FUNDAMENTALS,
    feature_names,
)
from auto_stock_trading.features.fundamental_features import (
    FUNDAMENTAL_FEATURE_NAMES,
    fundamental_features,
)


def _fact(rcept_no: str, *, eps: str | None, roe: str | None) -> AnnualFact:
    return AnnualFact(
        bsns_year=int(rcept_no[:4]) - 1,
        reprt_code="11011",
        fs_div="CFS",
        rcept_no=rcept_no,
        filed_on=disclosure_filed_on(rcept_no),
        roe=None if roe is None else Decimal(roe),
        eps=None if eps is None else Decimal(eps),
    )


def test_the_price_set_is_unchanged_and_the_new_set_adds_two() -> None:
    price = feature_names(FEATURE_SET_PRICE)
    combined = feature_names(FEATURE_SET_WITH_FUNDAMENTALS)

    assert FEATURE_SET_PRICE == "features-1"
    assert FEATURE_SET_WITH_FUNDAMENTALS == "features-2"
    assert len(price) == 23
    assert combined[: len(price)] == price
    assert combined[len(price) :] == FUNDAMENTAL_FEATURE_NAMES
    assert FUNDAMENTAL_FEATURE_NAMES == ("earnings_yield", "roe")


def test_an_unknown_feature_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="feature set"):
        _ = feature_names("features-99")


def test_earnings_yield_is_eps_over_the_close_and_roe_is_passed_through() -> None:
    facts = (_fact("20250310000001", eps="6605", roe="10.85"),)

    values = fundamental_features(facts, date(2025, 6, 2), Decimal(274_500))

    assert values is not None
    assert values["earnings_yield"] == Decimal(6605) / Decimal(274_500)
    assert values["roe"] == Decimal("10.85")


def test_a_report_filed_on_the_signal_date_is_not_used_yet() -> None:
    facts = (_fact("20250602000001", eps="6605", roe="10.85"),)

    assert fundamental_features(facts, date(2025, 6, 2), Decimal(274_500)) is None
    assert fundamental_features(facts, date(2025, 6, 3), Decimal(274_500)) is not None


def test_the_latest_known_report_wins() -> None:
    facts = (
        _fact("20240310000001", eps="1000", roe="5"),
        _fact("20250310000001", eps="2000", roe="9"),
    )

    early = fundamental_features(facts, date(2024, 6, 3), Decimal(100_000))
    later = fundamental_features(facts, date(2025, 6, 3), Decimal(100_000))

    assert early is not None
    assert early["roe"] == Decimal(5)
    assert later is not None
    assert later["roe"] == Decimal(9)


def test_a_missing_metric_produces_no_features_instead_of_a_filled_value() -> None:
    assert (
        fundamental_features(
            (_fact("20250310000001", eps="6605", roe=None),),
            date(2025, 6, 2),
            Decimal(274_500),
        )
        is None
    )
    assert (
        fundamental_features(
            (_fact("20250310000001", eps=None, roe="10.85"),),
            date(2025, 6, 2),
            Decimal(274_500),
        )
        is None
    )


def test_a_non_positive_close_produces_no_features() -> None:
    facts = (_fact("20250310000001", eps="6605", roe="10.85"),)

    assert fundamental_features(facts, date(2025, 6, 2), Decimal(0)) is None


def test_no_report_yet_produces_no_features() -> None:
    assert fundamental_features((), date(2025, 6, 2), Decimal(274_500)) is None
