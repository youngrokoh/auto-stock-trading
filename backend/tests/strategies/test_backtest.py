from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.strategies.backtest import (
    BacktestError,
    BacktestFailure,
    BacktestInputs,
    ExecutionBar,
    TradeSkipReason,
    run_backtest,
)
from auto_stock_trading.domain.strategies.costs import KrxMarket
from auto_stock_trading.domain.strategies.ma_rsi import (
    MaRsiParameters,
    SignalAction,
    SignalReason,
    StrategySignal,
    ma_rsi_signals,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_PARAMETERS: Final = MaRsiParameters(
    short_period=2,
    long_period=3,
    rsi_period=2,
    rsi_overbought=Decimal(90),
)
_CLOSES: Final = tuple(
    Decimal(value) for value in (10000, 9000, 8000, 9000, 12000, 13000, 12000, 9000)
)
_OPENS: Final = tuple(
    Decimal(value) for value in (9900, 9100, 8100, 8900, 11800, 12800, 12200, 9100)
)
_DATES: Final = tuple(date(2026, 8, 3) + timedelta(days=index) for index in range(len(_CLOSES)))
_INITIAL_CASH: Final = Decimal(1_000_000)


def _ma_rsi_signal_fn(
    dates: Sequence[date],
    closes: Sequence[Decimal],
) -> tuple[StrategySignal, ...]:
    return ma_rsi_signals(dates, closes, _PARAMETERS)


def _inputs(
    *,
    product_type: ProductType = ProductType.STOCK,
    dividends: dict[date, Decimal] | None = None,
    initial_cash: Decimal = _INITIAL_CASH,
) -> BacktestInputs:
    return BacktestInputs(
        trading_dates=_DATES,
        execution_bars={
            trading_date: ExecutionBar(open_price=open_price, close_price=close_price)
            for trading_date, open_price, close_price in zip(_DATES, _OPENS, _CLOSES, strict=True)
        },
        signal_closes=_CLOSES,
        benchmark_closes=_CLOSES,
        dividends=dividends or {},
        product_type=product_type,
        market=KrxMarket.KOSPI,
        initial_cash=initial_cash,
    )


def test_engine_executes_signals_at_next_open_with_costs() -> None:
    result = run_backtest(_inputs(), _ma_rsi_signal_fn)

    buy, first_sell, last_sell = result.trades
    assert buy.signal_date == _DATES[4]
    assert buy.execution_date == _DATES[5]
    assert buy.action is SignalAction.BUY
    assert buy.reason is SignalReason.GOLDEN_CROSS
    assert buy.quantity == 78
    assert buy.price == Decimal(12800)
    assert buy.gross_amount == Decimal(998_400)
    assert buy.fee == Decimal(199)
    assert buy.slippage == Decimal(998)
    assert buy.tax == Decimal(0)
    assert buy.skip_reason is None

    assert first_sell.signal_date == _DATES[5]
    assert first_sell.execution_date == _DATES[6]
    assert first_sell.action is SignalAction.SELL
    assert first_sell.quantity == 78
    assert first_sell.price == Decimal(12200)
    assert first_sell.gross_amount == Decimal(951_600)
    assert first_sell.fee == Decimal(190)
    assert first_sell.slippage == Decimal(951)
    assert first_sell.tax == Decimal(1903)

    assert last_sell.signal_date == _DATES[7]
    assert last_sell.execution_date is None
    assert last_sell.skip_reason is TradeSkipReason.WINDOW_END


def test_engine_tracks_equity_curve_and_metrics() -> None:
    result = run_backtest(_inputs(), _ma_rsi_signal_fn)

    navs = [point.nav for point in result.equity_curve]
    assert navs == [
        *([_INITIAL_CASH] * 5),
        Decimal(1_014_403),
        Decimal(948_959),
        Decimal(948_959),
    ]
    assert result.equity_curve[5].cash == Decimal(403)
    assert result.equity_curve[5].position_value == Decimal(1_014_000)

    metrics = result.metrics
    assert metrics.total_return_pct == Decimal("-5.10")
    assert metrics.pre_cost_return_pct == Decimal("-4.68")
    assert metrics.benchmark_return_pct == Decimal("-10.00")
    assert metrics.excess_return_pct == Decimal("4.90")
    assert metrics.mdd_pct == Decimal("-6.45")
    assert metrics.total_fee == Decimal(389)
    assert metrics.total_slippage == Decimal(1949)
    assert metrics.total_tax == Decimal(1903)
    assert metrics.trade_count == 2

    daily_returns = [navs[index] / navs[index - 1] - 1 for index in range(1, len(navs))]
    mean = sum(daily_returns, Decimal(0)) / len(daily_returns)
    variance = sum(((value - mean) ** 2 for value in daily_returns), Decimal(0)) / len(
        daily_returns
    )
    expected_sharpe = (mean / variance.sqrt() * Decimal(252).sqrt()).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )
    assert metrics.sharpe == expected_sharpe

    average_nav = sum(navs, Decimal(0)) / len(navs)
    years = Decimal(len(navs)) / 252
    expected_turnover = (Decimal(1_950_000) / average_nav / years * 100).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    assert metrics.turnover_pct == expected_turnover


def test_engine_credits_dividends_from_prior_day_holdings() -> None:
    result = run_backtest(
        _inputs(dividends={_DATES[6]: Decimal(50)}),
        _ma_rsi_signal_fn,
    )
    # d5에 78주 매수 → d6 락일에 직전 보유 78주 × 50원 = 3,900원 현금 반영 후 시가 매도.
    assert result.equity_curve[6].nav == Decimal(948_959) + Decimal(3_900)


def test_engine_skips_unexecutable_signals_with_reasons() -> None:
    def noisy_signals(
        dates: Sequence[date],
        closes: Sequence[Decimal],
    ) -> tuple[StrategySignal, ...]:
        _ = closes
        signals: list[StrategySignal] = []
        if len(dates) >= 2:
            signals.append(StrategySignal(dates[1], SignalAction.SELL, SignalReason.DEAD_CROSS))
        if len(dates) >= 3:
            signals.append(StrategySignal(dates[2], SignalAction.BUY, SignalReason.GOLDEN_CROSS))
        if len(dates) >= 4:
            signals.append(StrategySignal(dates[3], SignalAction.BUY, SignalReason.GOLDEN_CROSS))
        return tuple(signals)

    result = run_backtest(_inputs(), noisy_signals)
    sell, buy, second_buy = result.trades
    assert sell.skip_reason is TradeSkipReason.NO_POSITION
    assert buy.skip_reason is None
    assert second_buy.skip_reason is TradeSkipReason.ALREADY_POSITIONED


def test_engine_skips_buy_when_cash_cannot_cover_one_share() -> None:
    def buy_once(
        dates: Sequence[date],
        closes: Sequence[Decimal],
    ) -> tuple[StrategySignal, ...]:
        _ = closes
        if len(dates) >= 2:
            return (StrategySignal(dates[1], SignalAction.BUY, SignalReason.GOLDEN_CROSS),)
        return ()

    result = run_backtest(_inputs(initial_cash=Decimal(5000)), buy_once)
    (buy,) = result.trades
    assert buy.skip_reason is TradeSkipReason.INSUFFICIENT_CASH
    assert buy.quantity == 0


def test_engine_rejects_missing_execution_bar() -> None:
    inputs = _inputs()
    bars = dict(inputs.execution_bars)
    del bars[_DATES[3]]
    broken = BacktestInputs(
        trading_dates=inputs.trading_dates,
        execution_bars=bars,
        signal_closes=inputs.signal_closes,
        benchmark_closes=inputs.benchmark_closes,
        dividends=inputs.dividends,
        product_type=inputs.product_type,
        market=inputs.market,
        initial_cash=inputs.initial_cash,
    )
    with pytest.raises(BacktestError) as raised:
        _ = run_backtest(broken, _ma_rsi_signal_fn)
    assert raised.value.failure is BacktestFailure.MISSING_CONFIRMED_BAR


def test_engine_rejects_lookahead_signal_functions() -> None:
    def peeking_signals(
        dates: Sequence[date],
        closes: Sequence[Decimal],
    ) -> tuple[StrategySignal, ...]:
        if len(closes) >= 8 and closes[7] < closes[0]:
            return (StrategySignal(dates[1], SignalAction.BUY, SignalReason.GOLDEN_CROSS),)
        return ()

    with pytest.raises(BacktestError) as raised:
        _ = run_backtest(_inputs(), peeking_signals)
    assert raised.value.failure is BacktestFailure.LOOKAHEAD_INPUT


def test_engine_rejects_window_before_cost_rules() -> None:
    # 비용 규칙은 2020-01-01부터 있다(연구 가정 세트 포함). 그 앞은 여전히 거부한다.
    dates = tuple(date(2019, 6, 3) + timedelta(days=index) for index in range(len(_CLOSES)))
    inputs = BacktestInputs(
        trading_dates=dates,
        execution_bars={
            trading_date: ExecutionBar(open_price=open_price, close_price=close_price)
            for trading_date, open_price, close_price in zip(dates, _OPENS, _CLOSES, strict=True)
        },
        signal_closes=_CLOSES,
        benchmark_closes=_CLOSES,
        dividends={},
        product_type=ProductType.STOCK,
        market=KrxMarket.KOSPI,
        initial_cash=_INITIAL_CASH,
    )
    with pytest.raises(BacktestError) as raised:
        _ = run_backtest(inputs, _ma_rsi_signal_fn)
    assert raised.value.failure is BacktestFailure.UNCOVERED_COST_DATE
