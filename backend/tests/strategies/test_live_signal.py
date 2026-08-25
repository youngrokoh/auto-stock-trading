"""실주문 신호의 순수 규칙(ADR-0016).

두 가지를 고정한다. 실주문 회차는 **완결된 월말만**이고, 후보는 **목표와 보유의 차집합**이다.
"""

from datetime import date
from decimal import Decimal
from typing import Final

from auto_stock_trading.domain.orders.models import OrderSide
from auto_stock_trading.domain.strategies.live_signal import (
    completed_rebalance_dates,
    signal_candidates,
)
from auto_stock_trading.domain.strategies.ranking import RankedSymbol

_JULY: Final = (
    date(2026, 7, 29),
    date(2026, 7, 30),
    date(2026, 7, 31),
    date(2026, 8, 3),
    date(2026, 8, 4),
)


def test_only_month_ends_are_rebalance_dates() -> None:
    """다음 거래일이 다른 달일 때만 회차다."""
    assert completed_rebalance_dates(_JULY) == (date(2026, 7, 31),)


def test_the_window_end_is_not_a_rebalance_date() -> None:
    """백테스트는 창의 마지막 거래일을 회차로 본다(장부를 닫으려고). 실주문은 그러면 안 된다.

    T-1까지의 창에 그 규칙을 쓰면 **매일이 회차**가 되어 월말 전략이 일간 전략으로 바뀐다.
    """
    assert completed_rebalance_dates(_JULY[:2]) == ()
    assert date(2026, 8, 4) not in completed_rebalance_dates(_JULY)


def test_an_empty_calendar_has_no_rebalance() -> None:
    assert completed_rebalance_dates(()) == ()


def _target(symbol: str, score: str) -> RankedSymbol:
    return RankedSymbol(symbol=symbol, score=Decimal(score))


def test_targets_not_held_become_buy_candidates() -> None:
    candidates = signal_candidates((_target("069500", "0.3"), _target("133690", "0.2")), ())

    assert [(item.symbol, item.side) for item in candidates] == [
        ("069500", OrderSide.BUY),
        ("133690", OrderSide.BUY),
    ]


def test_holdings_not_targeted_become_sell_candidates() -> None:
    candidates = signal_candidates((_target("069500", "0.3"),), ("360750",))

    assert [(item.symbol, item.side) for item in candidates] == [
        ("069500", OrderSide.BUY),
        ("360750", OrderSide.SELL),
    ]


def test_a_held_target_produces_no_candidate() -> None:
    """비중 조정은 이 결정의 범위 밖이다(ADR-0016 결정 4). 교집합은 건드리지 않는다."""
    assert signal_candidates((_target("069500", "0.3"),), ("069500",)) == ()


def test_candidates_are_ordered_for_reproducibility() -> None:
    """같은 신호가 항상 같은 순서의 후보를 만든다 — 계획 재실행이 순서로 흔들리지 않는다."""
    candidates = signal_candidates(
        (_target("411060", "0.1"), _target("069500", "0.3")),
        ("453850", "133690"),
    )

    assert [(item.symbol, item.side) for item in candidates] == [
        ("069500", OrderSide.BUY),
        ("411060", OrderSide.BUY),
        ("133690", OrderSide.SELL),
        ("453850", OrderSide.SELL),
    ]
