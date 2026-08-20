from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.strategies.backtest import ExecutionBar
from auto_stock_trading.domain.strategies.costs import KrxMarket
from auto_stock_trading.domain.strategies.momentum import RankedSymbol, Rebalance
from auto_stock_trading.domain.strategies.portfolio_backtest import (
    PortfolioInputs,
    PortfolioSkipReason,
    run_portfolio_backtest,
)

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
    )


def _rebalance(day: date, *symbols: str) -> Rebalance:
    return Rebalance(
        signal_date=day,
        selected=tuple(RankedSymbol(symbol=symbol, momentum=Decimal("0.10")) for symbol in symbols),
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
