"""ETF 모멘텀 자산배분 전략 규칙(사용자 승인 2026-08-24).

승인된 규칙: 월말마다 12개월 수익률로 6자산을 서열화해 **상위 2자산 동일가중**, 수익률이 음수인
자리는 **현금성 ETF로 대피**한다. 상대 강도(서열)와 절대 모멘텀(음수 배제)을 함께 쓴다.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from auto_stock_trading.domain.strategies.etf_allocation import (
    CASH_PROXY_SYMBOL,
    EtfAllocationParameters,
    etf_allocation_rebalances,
)
from auto_stock_trading.domain.strategies.ranking import SymbolSeries

_LOOKBACK: Final = 5
_START: Final = date(2026, 1, 5)


def _calendar(days: int) -> tuple[date, ...]:
    return tuple(_START + timedelta(days=offset) for offset in range(days))


def _series(symbol: str, closes: dict[date, Decimal]) -> SymbolSeries:
    return SymbolSeries(symbol=symbol, closes=closes)


def _flat(symbol: str, calendar: tuple[date, ...], ratio: Decimal) -> SymbolSeries:
    """기준일 대비 `ratio`만큼 오른(내린) 종목. 마지막 날의 모멘텀이 ratio - 1이다."""
    closes = {day: Decimal(1000) for day in calendar[:-1]}
    closes[calendar[-1]] = Decimal(1000) * ratio
    return _series(symbol, closes)


def _parameters() -> EtfAllocationParameters:
    return EtfAllocationParameters(lookback_days=_LOOKBACK, holdings=2)


def test_the_top_two_positive_assets_are_selected() -> None:
    calendar = _calendar(_LOOKBACK + 1)
    signal_date = calendar[-1]
    universe = (
        _flat("069500", calendar, Decimal("1.30")),
        _flat("133690", calendar, Decimal("1.20")),
        _flat("360750", calendar, Decimal("1.10")),
        _flat(CASH_PROXY_SYMBOL, calendar, Decimal("1.01")),
    )

    (rebalance,) = etf_allocation_rebalances(
        (signal_date,),
        universe,
        _parameters(),
        calendar,
    )

    assert [item.symbol for item in rebalance.selected] == ["069500", "133690"]


def test_a_negative_asset_is_replaced_by_the_cash_proxy() -> None:
    """절대 모멘텀 조건: 수익률이 음수인 자리는 보유하지 않고 현금성으로 대피한다."""
    calendar = _calendar(_LOOKBACK + 1)
    signal_date = calendar[-1]
    universe = (
        _flat("069500", calendar, Decimal("1.30")),
        _flat("133690", calendar, Decimal("0.90")),
        _flat("360750", calendar, Decimal("0.80")),
        _flat(CASH_PROXY_SYMBOL, calendar, Decimal("1.01")),
    )

    (rebalance,) = etf_allocation_rebalances(
        (signal_date,),
        universe,
        _parameters(),
        calendar,
    )

    assert [item.symbol for item in rebalance.selected] == ["069500", CASH_PROXY_SYMBOL]


def test_both_slots_negative_leaves_a_single_cash_holding() -> None:
    """같은 종목을 두 자리에 넣을 수 없다.

    엔진은 NAV를 고정 보유 개수로 나누므로, 한 자리만 현금성이면 나머지는 미투자 현금으로 남는다.
    미투자 현금은 수익이 0이라 CD ETF보다 보수적이다 — 값을 만들지 않는 쪽을 택한다.
    """
    calendar = _calendar(_LOOKBACK + 1)
    signal_date = calendar[-1]
    universe = (
        _flat("069500", calendar, Decimal("0.70")),
        _flat("133690", calendar, Decimal("0.80")),
        _flat(CASH_PROXY_SYMBOL, calendar, Decimal("1.01")),
    )

    (rebalance,) = etf_allocation_rebalances(
        (signal_date,),
        universe,
        _parameters(),
        calendar,
    )

    assert [item.symbol for item in rebalance.selected] == [CASH_PROXY_SYMBOL]


def test_the_cash_proxy_already_in_the_top_two_is_not_duplicated() -> None:
    calendar = _calendar(_LOOKBACK + 1)
    signal_date = calendar[-1]
    universe = (
        _flat("069500", calendar, Decimal("1.30")),
        _flat(CASH_PROXY_SYMBOL, calendar, Decimal("1.01")),
        _flat("133690", calendar, Decimal("0.90")),
    )

    (rebalance,) = etf_allocation_rebalances(
        (signal_date,),
        universe,
        _parameters(),
        calendar,
    )

    assert [item.symbol for item in rebalance.selected] == ["069500", CASH_PROXY_SYMBOL]


def test_the_recorded_score_is_the_asset_actually_held() -> None:
    """대피한 자리의 점수는 현금성 ETF의 모멘텀이다. 배제된 자산의 점수를 남기면 감사가 틀린다."""
    calendar = _calendar(_LOOKBACK + 1)
    signal_date = calendar[-1]
    universe = (
        _flat("069500", calendar, Decimal("1.30")),
        _flat("133690", calendar, Decimal("0.90")),
        _flat(CASH_PROXY_SYMBOL, calendar, Decimal("1.02")),
    )

    (rebalance,) = etf_allocation_rebalances(
        (signal_date,),
        universe,
        _parameters(),
        calendar,
    )

    scores = {item.symbol: item.score for item in rebalance.selected}
    assert scores[CASH_PROXY_SYMBOL] == Decimal("0.02")


def test_a_missing_cash_proxy_momentum_skips_the_rebalance() -> None:
    """대피처의 값을 모르면 회차를 만들지 않는다. 대피할 수 없는 상태를 통과시키지 않는다."""
    calendar = _calendar(_LOOKBACK + 1)
    signal_date = calendar[-1]
    universe = (
        _flat("069500", calendar, Decimal("0.70")),
        _flat("133690", calendar, Decimal("0.80")),
        # 현금성 ETF의 봉이 없다.
    )

    assert (
        etf_allocation_rebalances(
            (signal_date,),
            universe,
            _parameters(),
            calendar,
        )
        == ()
    )


def test_the_warmup_window_makes_no_rebalance() -> None:
    """12개월 lookback이 달력 안에 없으면 회차를 만들지 않는다(v2 실측 결함과 같은 규칙)."""
    calendar = _calendar(_LOOKBACK)
    universe = (
        _flat("069500", calendar, Decimal("1.30")),
        _flat(CASH_PROXY_SYMBOL, calendar, Decimal("1.01")),
    )

    assert etf_allocation_rebalances((calendar[2],), universe, _parameters(), calendar) == ()
