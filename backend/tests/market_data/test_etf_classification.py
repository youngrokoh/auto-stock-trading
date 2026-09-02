"""ETF 업종 키 규칙(ADR-0021). 분류가 한도를 넓히는 방향이므로 넓혀도 되는 것만 넓힌다."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from auto_stock_trading.domain.market_data.etf_classification import (
    CLASSIFICATION_MAX_AGE,
    EtfIndexClassification,
    classification_sector,
)

_UNIT: Final = Decimal("1.00")
_AS_OF: Final = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)


def _fact(
    *,
    index_name: str = "S&P 500",
    tracking_multiple: Decimal = _UNIT,
    as_of: datetime = _AS_OF,
) -> EtfIndexClassification:
    return EtfIndexClassification(
        symbol="360750",
        index_name=index_name,
        tracking_multiple=tracking_multiple,
        source="KIS",
        as_of=as_of,
        received_at=as_of,
    )


def test_a_fresh_unit_multiple_etf_is_classified_by_its_index() -> None:
    assert classification_sector(_fact(), now=_AS_OF + timedelta(days=1)) == "S&P 500"


def test_the_index_string_is_used_as_the_source_gives_it() -> None:
    """정규화하면 "S&P 500"과 "S&P500"을 같게 만들 수도, 다른 지수를 잘못 합칠 수도 있다."""
    assert classification_sector(_fact(index_name=" KOSPI200 "), now=_AS_OF) == " KOSPI200 "


def test_leveraged_and_inverse_etfs_stay_unclassified() -> None:
    """추적배수가 1이 아니면 위험 성격이 다르다(결정 2)."""
    assert classification_sector(_fact(tracking_multiple=Decimal("2.00")), now=_AS_OF) is None
    assert classification_sector(_fact(tracking_multiple=Decimal("-1.00")), now=_AS_OF) is None


def test_a_stale_classification_is_unclassified() -> None:
    """관측이 오래되면 "언제 수집한 값인지 모르는 것"이 위험 입력이 된다(결정 4, 승인 30일)."""
    assert timedelta(days=30) == CLASSIFICATION_MAX_AGE
    boundary = _AS_OF + CLASSIFICATION_MAX_AGE
    assert classification_sector(_fact(), now=boundary) == "S&P 500"
    assert classification_sector(_fact(), now=boundary + timedelta(seconds=1)) is None


def test_a_blank_index_name_is_unclassified() -> None:
    """빈 문자열을 업종 키로 쓰면 빈 값끼리 묶여 의미 없는 한도가 생긴다."""
    assert classification_sector(_fact(index_name="  "), now=_AS_OF) is None
