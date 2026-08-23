"""상장 주식종류 짝짓기(종목 유니버스 계약 §주식종류 사실). 순수 함수다.

짝짓기는 단축코드 앞 5자리라는 KRX 관행에 기댄다. 원천이 보장하는 규칙이 아니므로 예외는
추측하지 않고 거부하고 보고한다.
"""

from datetime import UTC, datetime

from auto_stock_trading.domain.market_data.share_classes import (
    ShareClassKind,
    pair_share_classes,
)
from auto_stock_trading.domain.market_data.stocks import StockListing

_NOW = datetime(2026, 8, 23, 4, 0, tzinfo=UTC)


def _listing(symbol: str, name: str) -> StockListing:
    return StockListing(
        symbol=symbol,
        isin=f"KR7{symbol}003",
        name=name,
        source="KIS_MASTER",
        received_at=_NOW,
    )


def test_a_company_without_preferred_shares_yields_one_common_class() -> None:
    result = pair_share_classes((_listing("005930", "삼성전자"),))

    assert result.refused == ()
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.common_symbol == "005930"
    assert [(item.symbol, item.class_kind) for item in group.classes] == [
        ("005930", ShareClassKind.COMMON)
    ]
    assert group.has_preferred is False


def test_preferred_shares_are_paired_by_the_five_digit_prefix() -> None:
    result = pair_share_classes(
        (
            _listing("005380", "현대차"),
            _listing("005385", "현대차우"),
            _listing("005387", "현대차2우B"),
            _listing("005389", "현대차3우B"),
        )
    )

    assert result.refused == ()
    group = result.groups[0]
    assert group.common_symbol == "005380"
    assert group.has_preferred is True
    assert [item.symbol for item in group.classes] == ["005380", "005385", "005387", "005389"]
    assert [item.class_kind for item in group.classes[1:]] == [ShareClassKind.PREFERRED] * 3


def test_an_alphanumeric_preferred_code_is_paired() -> None:
    """실측: 우선주 단축코드에 영문자가 섞인다(`00088K` 한화3우B)."""
    result = pair_share_classes((_listing("000880", "한화"), _listing("00088K", "한화3우B")))

    assert result.refused == ()
    assert [item.symbol for item in result.groups[0].classes] == ["000880", "00088K"]


def test_a_preferred_share_without_a_common_pair_is_refused() -> None:
    result = pair_share_classes((_listing("005385", "현대차우"),))

    assert result.groups == ()
    assert result.refused == (("00538", "no common share for the prefix"),)


def test_two_common_shares_on_one_prefix_refuse_the_whole_group() -> None:
    """접두 공유는 관행이다. 보통주가 둘이면 어느 쪽 짝인지 결정할 수 없다."""
    result = pair_share_classes(
        (
            _listing("005380", "현대차"),
            _listing("005380", "현대차"),
            _listing("005385", "현대차우"),
        )
    )

    assert result.groups == ()
    assert result.refused == (("00538", "more than one common share for the prefix"),)


def test_one_refused_group_does_not_drop_the_others() -> None:
    result = pair_share_classes(
        (
            _listing("005930", "삼성전자"),
            _listing("005935", "삼성전자우"),
            _listing("005385", "현대차우"),
        )
    )

    assert [group.common_symbol for group in result.groups] == ["005930"]
    assert [prefix for prefix, _ in result.refused] == ["00538"]


def test_groups_are_ordered_by_the_common_symbol() -> None:
    result = pair_share_classes(
        (
            _listing("005930", "삼성전자"),
            _listing("000100", "유한양행"),
            _listing("000105", "유한양행우"),
        )
    )

    assert [group.common_symbol for group in result.groups] == ["000100", "005930"]
