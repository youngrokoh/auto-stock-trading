"""다종목 포트폴리오 백테스트 엔진(백테스트 계약 v2).

단일 종목 엔진(`backtest.py`)은 그대로 둔다. 6단계에서 실데이터로 검증된 경로이므로
다종목 규칙을 그 안에 섞지 않는다. 비용·지표 정의는 공용 모듈을 함께 쓴다.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.strategies.backtest_metrics import (
    EquityPoint,
    MetricsInputs,
    backtest_metrics,
)
from auto_stock_trading.domain.strategies.costs import (
    TradeSide,
    cost_rule_set_for,
    trade_costs,
)

if TYPE_CHECKING:
    from auto_stock_trading.domain.strategies.costs import TradeCosts

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from auto_stock_trading.domain.market_data.models import ProductType
    from auto_stock_trading.domain.strategies.backtest import ExecutionBar
    from auto_stock_trading.domain.strategies.backtest_metrics import BacktestMetrics
    from auto_stock_trading.domain.strategies.costs import KrxMarket
    from auto_stock_trading.domain.strategies.momentum import Rebalance

PORTFOLIO_ENGINE_VERSION: Final = "portfolio-1"

_BUY: Final = "buy"
_SELL: Final = "sell"


class PortfolioSkipReason(StrEnum):
    MISSING_CONFIRMED_BAR = "missing_confirmed_bar"
    INSUFFICIENT_CASH = "insufficient_cash"
    NO_POSITION = "no_position"
    ALREADY_AT_TARGET = "already_at_target"


@dataclass(frozen=True, slots=True)
class PortfolioInputs:
    trading_dates: Sequence[date]
    bars: Mapping[str, Mapping[date, ExecutionBar]]
    benchmark_closes: Sequence[Decimal]
    dividends: Mapping[str, Mapping[date, Decimal]]
    product_types: Mapping[str, ProductType]
    market: KrxMarket
    initial_cash: Decimal
    holdings: int


@dataclass(frozen=True, slots=True)
class PortfolioTrade:
    sequence: int
    symbol: str
    signal_date: date
    execution_date: date | None
    action: str
    quantity: int
    price: Decimal | None
    gross_amount: Decimal
    fee: Decimal
    slippage: Decimal
    tax: Decimal
    skip_reason: PortfolioSkipReason | None


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    trades: tuple[PortfolioTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    metrics: BacktestMetrics


@dataclass(slots=True)
class _Book:
    cash: Decimal
    positions: dict[str, int] = field(default_factory=dict[str, int])
    total_fee: Decimal = Decimal(0)
    total_slippage: Decimal = Decimal(0)
    total_tax: Decimal = Decimal(0)
    traded_amount: Decimal = Decimal(0)
    executed: int = 0


def _skip(
    sequence: int,
    symbol: str,
    signal_date: date,
    action: str,
    reason: PortfolioSkipReason,
) -> PortfolioTrade:
    return PortfolioTrade(
        sequence=sequence,
        symbol=symbol,
        signal_date=signal_date,
        execution_date=None,
        action=action,
        quantity=0,
        price=None,
        gross_amount=Decimal(0),
        fee=Decimal(0),
        slippage=Decimal(0),
        tax=Decimal(0),
        skip_reason=reason,
    )


def _last_close(inputs: PortfolioInputs, symbol: str, upto: date) -> Decimal | None:
    """거래정지 등으로 당일 봉이 없으면 마지막으로 알려진 확정 종가를 쓴다."""
    closes = inputs.bars.get(symbol, {})
    candidates = [day for day in closes if day <= upto]
    if not candidates:
        return None
    return closes[max(candidates)].close_price


@dataclass(frozen=True, slots=True)
class _Fill:
    symbol: str
    signal_date: date
    execution_date: date
    open_price: Decimal


def _execute_sell(
    inputs: PortfolioInputs,
    book: _Book,
    sequence: int,
    fill: _Fill,
) -> PortfolioTrade:
    quantity = book.positions.get(fill.symbol, 0)
    if quantity == 0:
        return _skip(
            sequence, fill.symbol, fill.signal_date, _SELL, PortfolioSkipReason.NO_POSITION
        )
    rule_set = cost_rule_set_for(fill.execution_date)
    gross = fill.open_price * quantity
    costs = trade_costs(
        rule_set,
        inputs.product_types[fill.symbol],
        inputs.market,
        TradeSide.SELL,
        gross,
    )
    book.cash += gross - costs.total
    del book.positions[fill.symbol]
    return _record(book, sequence, _Execution(fill, _SELL, quantity, gross, costs))


def _execute_buy(
    inputs: PortfolioInputs,
    book: _Book,
    sequence: int,
    fill: _Fill,
    budget: Decimal,
) -> PortfolioTrade:
    """목표 금액 안에서 비용을 포함해 살 수 있는 최대 정수 수량을 산다."""
    rule_set = cost_rule_set_for(fill.execution_date)
    spendable = min(budget, book.cash)
    quantity = int(spendable / fill.open_price)
    while quantity > 0:
        gross = fill.open_price * quantity
        costs = trade_costs(
            rule_set,
            inputs.product_types[fill.symbol],
            inputs.market,
            TradeSide.BUY,
            gross,
        )
        if gross + costs.total <= spendable:
            book.cash -= gross + costs.total
            book.positions[fill.symbol] = book.positions.get(fill.symbol, 0) + quantity
            return _record(book, sequence, _Execution(fill, _BUY, quantity, gross, costs))
        quantity -= 1
    return _skip(
        sequence,
        fill.symbol,
        fill.signal_date,
        _BUY,
        PortfolioSkipReason.INSUFFICIENT_CASH,
    )


@dataclass(frozen=True, slots=True)
class _Execution:
    """체결 한 건의 결과. 인자를 묶어 기록 함수를 단순하게 유지한다."""

    fill: _Fill
    action: str
    quantity: int
    gross: Decimal
    costs: TradeCosts


def _record(book: _Book, sequence: int, execution: _Execution) -> PortfolioTrade:
    fill = execution.fill
    action = execution.action
    quantity = execution.quantity
    gross = execution.gross
    costs = execution.costs
    book.total_fee += costs.fee
    book.total_slippage += costs.slippage
    book.total_tax += costs.tax
    book.traded_amount += gross
    book.executed += 1
    return PortfolioTrade(
        sequence=sequence,
        symbol=fill.symbol,
        signal_date=fill.signal_date,
        execution_date=fill.execution_date,
        action=action,
        quantity=quantity,
        price=fill.open_price,
        gross_amount=gross,
        fee=costs.fee,
        slippage=costs.slippage,
        tax=costs.tax,
        skip_reason=None,
    )


def _execution_date(trading_dates: Sequence[date], signal_date: date) -> date | None:
    """회차 전체가 같은 날 체결된다. 그날 봉이 없는 종목은 그 회차에서 빠진다."""
    for day in trading_dates:
        if day > signal_date:
            return day
    return None


def _nav(inputs: PortfolioInputs, book: _Book, day: date) -> tuple[Decimal, Decimal]:
    position_value = Decimal(0)
    for symbol, quantity in book.positions.items():
        close = _last_close(inputs, symbol, day)
        if close is not None:
            position_value += close * quantity
    return book.cash, position_value


def _credit_dividends(inputs: PortfolioInputs, book: _Book, day: date) -> None:
    for symbol, quantity in book.positions.items():
        amount = inputs.dividends.get(symbol, {}).get(day)
        if amount is not None:
            book.cash += amount * quantity


def _rebalance_trades(
    inputs: PortfolioInputs,
    book: _Book,
    rebalance: Rebalance,
    execution_date: date,
    sequence: int,
) -> tuple[list[PortfolioTrade], int]:
    trades: list[PortfolioTrade] = []
    selected = tuple(item.symbol for item in rebalance.selected)
    target_cash, target_positions = _nav(inputs, book, execution_date)
    target_value = (target_cash + target_positions) / inputs.holdings
    for symbol in sorted(set(book.positions) - set(selected)):
        bar = inputs.bars.get(symbol, {}).get(execution_date)
        if bar is None:
            trades.append(
                _skip(
                    sequence,
                    symbol,
                    rebalance.signal_date,
                    _SELL,
                    PortfolioSkipReason.MISSING_CONFIRMED_BAR,
                )
            )
        else:
            trades.append(
                _execute_sell(
                    inputs,
                    book,
                    sequence,
                    _Fill(symbol, rebalance.signal_date, execution_date, bar.open_price),
                )
            )
        sequence += 1
    for symbol in selected:
        bar = inputs.bars.get(symbol, {}).get(execution_date)
        if bar is None:
            trades.append(
                _skip(
                    sequence,
                    symbol,
                    rebalance.signal_date,
                    _BUY,
                    PortfolioSkipReason.MISSING_CONFIRMED_BAR,
                )
            )
            sequence += 1
            continue
        held_value = bar.close_price * book.positions.get(symbol, 0)
        budget = target_value - held_value
        if budget <= 0:
            trades.append(
                _skip(
                    sequence,
                    symbol,
                    rebalance.signal_date,
                    _BUY,
                    PortfolioSkipReason.ALREADY_AT_TARGET,
                )
            )
        else:
            trades.append(
                _execute_buy(
                    inputs,
                    book,
                    sequence,
                    _Fill(symbol, rebalance.signal_date, execution_date, bar.open_price),
                    budget,
                )
            )
        sequence += 1
    return trades, sequence


def run_portfolio_backtest(
    inputs: PortfolioInputs,
    rebalances: Sequence[Rebalance],
) -> PortfolioResult:
    dates = tuple(inputs.trading_dates)
    window = set(dates)
    for rebalance in rebalances:
        if rebalance.signal_date not in window:
            message = f"rebalance signal outside the window at {rebalance.signal_date.isoformat()}"
            raise ValueError(message)
    scheduled: dict[date, Rebalance] = {}
    for rebalance in rebalances:
        execution_date = _execution_date(dates, rebalance.signal_date)
        if execution_date is not None:
            scheduled[execution_date] = rebalance
    book = _Book(cash=inputs.initial_cash)
    trades: list[PortfolioTrade] = []
    curve: list[EquityPoint] = []
    sequence = 1
    for day in dates:
        _credit_dividends(inputs, book, day)
        rebalance = scheduled.get(day)
        if rebalance is not None:
            executed, sequence = _rebalance_trades(inputs, book, rebalance, day, sequence)
            trades.extend(executed)
        cash, position_value = _nav(inputs, book, day)
        curve.append(
            EquityPoint(
                trading_date=day,
                cash=cash,
                position_value=position_value,
                nav=cash + position_value,
            )
        )
    metrics = backtest_metrics(
        MetricsInputs(
            initial_cash=inputs.initial_cash,
            benchmark_closes=inputs.benchmark_closes,
            total_fee=book.total_fee,
            total_slippage=book.total_slippage,
            total_tax=book.total_tax,
            traded_amount=book.traded_amount,
            executed_count=book.executed,
        ),
        tuple(curve),
    )
    return PortfolioResult(trades=tuple(trades), equity_curve=tuple(curve), metrics=metrics)
