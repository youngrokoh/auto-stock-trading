from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.strategies.backtest import ExecutionBar
from auto_stock_trading.domain.strategies.costs import KrxMarket
from auto_stock_trading.domain.strategies.portfolio_backtest import (
    PortfolioInputs,
    PortfolioSkipReason,
    run_portfolio_backtest,
)
from auto_stock_trading.domain.strategies.ranking import RankedSymbol, Rebalance

_DATES: Final = (
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 6),
    date(2025, 1, 7),
)
_CASH: Final = Decimal(10_000_000)


def _bars(prices: dict[str, tuple[str, ...]]) -> dict[str, dict[date, ExecutionBar]]:
    return {
        symbol: {
            day: ExecutionBar(open_price=Decimal(value), close_price=Decimal(value))
            for day, value in zip(_DATES, values, strict=True)
        }
        for symbol, values in prices.items()
    }


def _inputs(
    bars: dict[str, dict[date, ExecutionBar]],
    *,
    holdings: int = 2,
    dividends: dict[str, dict[date, Decimal]] | None = None,
    trim_to_target: bool = False,
) -> PortfolioInputs:
    return PortfolioInputs(
        trading_dates=_DATES,
        bars=bars,
        benchmark_closes=(Decimal(100), Decimal(100), Decimal(100), Decimal(100)),
        dividends=dividends or {},
        product_types=dict.fromkeys(bars, ProductType.STOCK),
        market=KrxMarket.KOSPI,
        initial_cash=_CASH,
        holdings=holdings,
        trim_to_target=trim_to_target,
    )


def _rebalance(day: date, *symbols: str) -> Rebalance:
    return Rebalance(
        signal_date=day,
        selected=tuple(RankedSymbol(symbol=symbol, score=Decimal("0.10")) for symbol in symbols),
    )


def test_a_rebalance_buys_the_selected_symbols_at_the_next_open_equally() -> None:
    bars = _bars({"000001": ("100", "100", "100", "100"), "000002": ("200",) * 4})

    result = run_portfolio_backtest(_inputs(bars), (_rebalance(_DATES[0], "000001", "000002"),))

    executed = [trade for trade in result.trades if trade.skip_reason is None]
    assert [(trade.symbol, trade.execution_date, trade.quantity) for trade in executed] == [
        # 목표 금액은 NAV의 1/2 = 5,000,000. 비용을 포함해 살 수 있는 최대 정수 수량이다.
        ("000001", _DATES[1], 49_940),
        ("000002", _DATES[1], 24_970),
    ]
    assert result.metrics.trade_count == 2


def test_holdings_outside_the_new_selection_are_sold_before_buying() -> None:
    bars = _bars({"000001": ("100",) * 4, "000002": ("100",) * 4})

    result = run_portfolio_backtest(
        _inputs(bars, holdings=1),
        (_rebalance(_DATES[0], "000001"), _rebalance(_DATES[1], "000002")),
    )

    actions = [
        (trade.symbol, trade.action, trade.execution_date)
        for trade in result.trades
        if trade.skip_reason is None
    ]
    assert actions == [
        ("000001", "buy", _DATES[1]),
        ("000001", "sell", _DATES[2]),
        ("000002", "buy", _DATES[2]),
    ]
    # 매도가 먼저 실행돼 현금이 생긴 뒤 매수가 이뤄진다.
    assert actions.index(("000001", "sell", _DATES[2])) < actions.index(
        ("000002", "buy", _DATES[2])
    )


def test_a_symbol_without_a_bar_on_the_execution_date_is_skipped_and_recorded() -> None:
    bars = _bars({"000001": ("100",) * 4})
    bars["000002"] = {_DATES[0]: ExecutionBar(Decimal(100), Decimal(100))}

    result = run_portfolio_backtest(_inputs(bars), (_rebalance(_DATES[0], "000001", "000002"),))

    skipped = [trade for trade in result.trades if trade.skip_reason is not None]
    assert [(trade.symbol, trade.skip_reason) for trade in skipped] == [
        ("000002", PortfolioSkipReason.MISSING_CONFIRMED_BAR)
    ]


def test_dividends_are_credited_on_the_ex_date_for_the_prior_day_holding() -> None:
    bars = _bars({"000001": ("100",) * 4})
    dividends = {"000001": {_DATES[3]: Decimal(5)}}

    with_dividend = run_portfolio_backtest(
        _inputs(bars, holdings=1, dividends=dividends),
        (_rebalance(_DATES[0], "000001"),),
    )
    without = run_portfolio_backtest(
        _inputs(bars, holdings=1),
        (_rebalance(_DATES[0], "000001"),),
    )

    quantity = next(t.quantity for t in with_dividend.trades if t.skip_reason is None)
    difference = with_dividend.equity_curve[-1].nav - without.equity_curve[-1].nav
    assert difference == Decimal(5) * quantity


def test_the_nav_curve_covers_every_trading_date() -> None:
    bars = _bars({"000001": ("100",) * 4})

    result = run_portfolio_backtest(_inputs(bars, holdings=1), (_rebalance(_DATES[0], "000001"),))

    assert [point.trading_date for point in result.equity_curve] == list(_DATES)
    assert result.equity_curve[0].nav == _CASH


def test_a_rebalance_signal_outside_the_window_is_refused() -> None:
    bars = _bars({"000001": ("100",) * 4})

    with pytest.raises(ValueError, match="outside"):
        _ = run_portfolio_backtest(
            _inputs(bars, holdings=1),
            (_rebalance(date(2024, 12, 31), "000001"),),
        )


def test_a_retained_symbol_is_not_sold_when_it_leaves_the_selection() -> None:
    """교체 임계(ML 신호 계약 §예측 안정화). 보유 중이고 유지 허용이면 팔지 않는다."""
    first = Rebalance(
        signal_date=_DATES[0],
        selected=(RankedSymbol(symbol="000100", score=Decimal(1)),),
    )
    # 두 번째 회차에서 000100이 선정에서 빠지지만 유지 허용 목록에 있다.
    second = Rebalance(
        signal_date=_DATES[2],
        selected=(RankedSymbol(symbol="000200", score=Decimal(1)),),
        retained=("000100",),
    )

    bars = _bars({"000100": ("100",) * 4, "000200": ("200",) * 4})
    result = run_portfolio_backtest(_inputs(bars, holdings=2), (first, second))

    sells = [trade for trade in result.trades if trade.action == "sell"]
    assert all(trade.symbol != "000100" for trade in sells)
    # 유지 허용은 보유만 이어간다. 목표 금액까지 추가로 사지 않는다.
    buys = [trade for trade in result.trades if trade.action == "buy" and trade.quantity > 0]
    assert {trade.symbol for trade in buys} == {"000100", "000200"}
    assert sum(1 for trade in buys if trade.symbol == "000100") == 1


def test_a_symbol_not_held_is_not_bought_just_because_it_is_retained() -> None:
    rebalance = Rebalance(
        signal_date=_DATES[0],
        selected=(RankedSymbol(symbol="000100", score=Decimal(1)),),
        retained=("000200",),
    )

    bars = _bars({"000100": ("100",) * 4, "000200": ("200",) * 4})
    result = run_portfolio_backtest(_inputs(bars, holdings=2), (rebalance,))

    executed = {trade.symbol for trade in result.trades if trade.quantity > 0}
    assert executed == {"000100"}


def test_trimming_sells_the_excess_of_a_still_selected_holding() -> None:
    """ETF 자산배분의 동일가중은 오른 자산을 되팔아야 성립한다(2026-08-24 승인).

    기본값은 트리밍하지 않는다(회전율을 줄이려는 기존 의도). 켠 경우에만 목표 초과분을 팔아 부족한
    자리를 채운다 — 실측에서 41회 중 20회가 `insufficient_cash`로 두 번째 자리를 못 채웠다.
    """
    bars = _bars(
        {
            "000010": ("1000", "1000", "3000", "3000"),
            "000020": ("1000", "1000", "1000", "1000"),
        }
    )
    inputs = _inputs(bars, trim_to_target=True)

    result = run_portfolio_backtest(
        inputs,
        (
            _rebalance(_DATES[0], "000010"),
            _rebalance(_DATES[1], "000010", "000020"),
        ),
    )

    trims = [
        trade
        for trade in result.trades
        if trade.action == "sell" and trade.symbol == "000010" and trade.quantity > 0
    ]
    assert trims, "목표를 넘은 보유가 트리밍되지 않았다"
    # 트리밍 뒤에는 두 자리를 모두 채울 현금이 생긴다.
    assert all(
        trade.skip_reason is not PortfolioSkipReason.INSUFFICIENT_CASH for trade in result.trades
    )


def test_trimming_is_off_by_default() -> None:
    """v2·v3 실행의 재현성을 지킨다. 기본값이 바뀌면 저장된 실행과 결과가 달라진다."""
    bars = _bars(
        {
            "000010": ("1000", "1000", "3000", "3000"),
            "000020": ("1000", "1000", "1000", "1000"),
        }
    )
    inputs = _inputs(bars)

    result = run_portfolio_backtest(
        inputs,
        (
            _rebalance(_DATES[0], "000010"),
            _rebalance(_DATES[1], "000010", "000020"),
        ),
    )

    assert not [
        trade
        for trade in result.trades
        if trade.action == "sell" and trade.symbol == "000010" and trade.quantity > 0
    ]


def test_an_excess_smaller_than_one_share_records_nothing() -> None:
    """1주 미만 초과는 결정이 없었던 것이다.

    `no_position`으로 기록하면 사유가 원인을 잘못 말한다 — 보유는 있고 초과분이 작을 뿐이다.
    실측에서 이 형태로 4건이 남았다.
    """
    bars = _bars(
        {
            "000010": ("1000", "1000", "1001", "1001"),
            "000020": ("1000", "1000", "1000", "1000"),
        }
    )
    inputs = _inputs(bars, trim_to_target=True)

    result = run_portfolio_backtest(
        inputs,
        (
            _rebalance(_DATES[0], "000010", "000020"),
            _rebalance(_DATES[1], "000010", "000020"),
        ),
    )

    assert not [
        trade for trade in result.trades if trade.skip_reason is PortfolioSkipReason.NO_POSITION
    ]
