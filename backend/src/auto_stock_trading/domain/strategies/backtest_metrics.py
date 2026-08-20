"""성과 지표 계산. 단일 종목 엔진과 포트폴리오 엔진이 같은 정의를 쓴다.

지표 정의는 백테스트 계약의 성과 지표 표가 유일한 기준이다. 두 엔진이 각자 계산하면
같은 이름의 지표가 서로 다른 값을 갖게 된다.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

_PERCENT_PLACES: Final = Decimal("0.01")
_SHARPE_PLACES: Final = Decimal("0.0001")
_TRADING_DAYS_PER_YEAR: Final = Decimal(252)


def percent(value: Decimal) -> Decimal:
    return (value * 100).quantize(_PERCENT_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class EquityPoint:
    trading_date: date
    cash: Decimal
    position_value: Decimal
    nav: Decimal


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    total_return_pct: Decimal
    pre_cost_return_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal
    mdd_pct: Decimal
    sharpe: Decimal | None
    turnover_pct: Decimal
    total_fee: Decimal
    total_slippage: Decimal
    total_tax: Decimal
    trade_count: int


@dataclass(frozen=True, slots=True)
class MetricsInputs:
    """지표 계산에 필요한 최소 입력. 엔진의 내부 상태 모양에 의존하지 않는다."""

    initial_cash: Decimal
    benchmark_closes: Sequence[Decimal]
    total_fee: Decimal
    total_slippage: Decimal
    total_tax: Decimal
    traded_amount: Decimal
    executed_count: int


def _max_drawdown(equity_curve: Sequence[EquityPoint]) -> Decimal:
    peak = equity_curve[0].nav
    drawdown = Decimal(0)
    for point in equity_curve:
        peak = max(peak, point.nav)
        drawdown = min(drawdown, point.nav / peak - 1)
    return drawdown


def _sharpe(equity_curve: Sequence[EquityPoint]) -> Decimal | None:
    daily_returns = [
        equity_curve[index].nav / equity_curve[index - 1].nav - 1
        for index in range(1, len(equity_curve))
    ]
    if not daily_returns:
        return None
    mean = sum(daily_returns, Decimal(0)) / len(daily_returns)
    variance = sum(((value - mean) ** 2 for value in daily_returns), Decimal(0)) / len(
        daily_returns
    )
    if variance <= 0:
        return None
    return (mean / variance.sqrt() * _TRADING_DAYS_PER_YEAR.sqrt()).quantize(
        _SHARPE_PLACES,
        rounding=ROUND_HALF_UP,
    )


def backtest_metrics(
    inputs: MetricsInputs,
    equity_curve: Sequence[EquityPoint],
) -> BacktestMetrics:
    initial = inputs.initial_cash
    final_nav = equity_curve[-1].nav
    total_costs = inputs.total_fee + inputs.total_slippage + inputs.total_tax
    total_return = percent((final_nav - initial) / initial)
    benchmark_return = percent(inputs.benchmark_closes[-1] / inputs.benchmark_closes[0] - 1)
    average_nav = sum((point.nav for point in equity_curve), Decimal(0)) / len(equity_curve)
    years = Decimal(len(equity_curve)) / _TRADING_DAYS_PER_YEAR
    turnover = (inputs.traded_amount / average_nav / years * 100).quantize(
        _PERCENT_PLACES,
        rounding=ROUND_HALF_UP,
    )
    return BacktestMetrics(
        total_return_pct=total_return,
        pre_cost_return_pct=percent((final_nav + total_costs - initial) / initial),
        benchmark_return_pct=benchmark_return,
        excess_return_pct=total_return - benchmark_return,
        mdd_pct=percent(_max_drawdown(equity_curve)),
        sharpe=_sharpe(equity_curve),
        turnover_pct=turnover,
        total_fee=inputs.total_fee,
        total_slippage=inputs.total_slippage,
        total_tax=inputs.total_tax,
        trade_count=inputs.executed_count,
    )
