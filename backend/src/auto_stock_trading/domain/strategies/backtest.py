from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

from auto_stock_trading.domain.strategies.backtest_metrics import (
    BacktestMetrics,
    EquityPoint,
    MetricsInputs,
    backtest_metrics,
)
from auto_stock_trading.domain.strategies.costs import (
    TradeSide,
    UncoveredCostDateError,
    cost_rule_set_for,
    trade_costs,
)
from auto_stock_trading.domain.strategies.ma_rsi import SignalAction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date

    from auto_stock_trading.domain.market_data.models import ProductType
    from auto_stock_trading.domain.strategies.costs import KrxMarket
    from auto_stock_trading.domain.strategies.ma_rsi import SignalReason, StrategySignal

ENGINE_ALGORITHM_VERSION: Final = "backtest-1"

type SignalFunction = Callable[
    [Sequence[date], Sequence[Decimal]],
    tuple[StrategySignal, ...],
]

_PERCENT_PLACES: Final = Decimal("0.01")
_SHARPE_PLACES: Final = Decimal("0.0001")
_TRADING_DAYS_PER_YEAR: Final = Decimal(252)


class BacktestFailure(StrEnum):
    MISSING_CONFIRMED_BAR = "missing_confirmed_bar"
    MISSING_ADJUSTED_DATASET = "missing_adjusted_dataset"
    MISSING_CALENDAR_COVERAGE = "missing_calendar_coverage"
    UNCOVERED_COST_DATE = "uncovered_cost_date"
    LOOKAHEAD_INPUT = "lookahead_input"
    INVALID_INPUT = "invalid_input"


class TradeSkipReason(StrEnum):
    WINDOW_END = "window_end"
    ALREADY_POSITIONED = "already_positioned"
    NO_POSITION = "no_position"
    INSUFFICIENT_CASH = "insufficient_cash"


@dataclass(frozen=True, slots=True)
class BacktestError(Exception):
    failure: BacktestFailure
    detail: str

    @override
    def __str__(self) -> str:
        return f"{self.failure.value}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ExecutionBar:
    open_price: Decimal
    close_price: Decimal


@dataclass(frozen=True, slots=True)
class BacktestInputs:
    trading_dates: Sequence[date]
    execution_bars: Mapping[date, ExecutionBar]
    signal_closes: Sequence[Decimal]
    benchmark_closes: Sequence[Decimal]
    dividends: Mapping[date, Decimal]
    product_type: ProductType
    market: KrxMarket
    initial_cash: Decimal


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    sequence: int
    signal_date: date
    execution_date: date | None
    action: SignalAction
    reason: SignalReason
    quantity: int
    price: Decimal | None
    gross_amount: Decimal
    fee: Decimal
    slippage: Decimal
    tax: Decimal
    skip_reason: TradeSkipReason | None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    metrics: BacktestMetrics


def _validate_inputs(inputs: BacktestInputs) -> None:
    dates = inputs.trading_dates
    if not dates:
        raise BacktestError(BacktestFailure.INVALID_INPUT, "trading_dates must not be empty")
    if inputs.initial_cash <= 0:
        raise BacktestError(BacktestFailure.INVALID_INPUT, "initial_cash must be positive")
    if len(inputs.signal_closes) != len(dates) or len(inputs.benchmark_closes) != len(dates):
        raise BacktestError(
            BacktestFailure.INVALID_INPUT,
            "signal and benchmark series must align with trading_dates",
        )
    for index in range(1, len(dates)):
        if dates[index] <= dates[index - 1]:
            raise BacktestError(
                BacktestFailure.INVALID_INPUT,
                "trading_dates must be strictly increasing",
            )
    for trading_date in dates:
        if trading_date not in inputs.execution_bars:
            raise BacktestError(
                BacktestFailure.MISSING_CONFIRMED_BAR,
                f"no confirmed bar for {trading_date.isoformat()}",
            )
    try:
        _ = cost_rule_set_for(dates[0])
    except UncoveredCostDateError as error:
        raise BacktestError(BacktestFailure.UNCOVERED_COST_DATE, str(error)) from error


def _collect_signals(
    inputs: BacktestInputs,
    signal_fn: SignalFunction,
) -> tuple[StrategySignal, ...]:
    dates = inputs.trading_dates
    date_index = {trading_date: index for index, trading_date in enumerate(dates)}
    signals = signal_fn(dates, inputs.signal_closes)
    for signal in signals:
        index = date_index.get(signal.signal_date)
        if index is None:
            raise BacktestError(
                BacktestFailure.LOOKAHEAD_INPUT,
                f"signal outside the window at {signal.signal_date.isoformat()}",
            )
        prefix_signals = signal_fn(dates[: index + 1], inputs.signal_closes[: index + 1])
        if signal not in prefix_signals:
            raise BacktestError(
                BacktestFailure.LOOKAHEAD_INPUT,
                f"signal at {signal.signal_date.isoformat()} depends on future data",
            )
    return signals


@dataclass(slots=True)
class _Account:
    cash: Decimal
    shares: int = 0
    total_fee: Decimal = Decimal(0)
    total_slippage: Decimal = Decimal(0)
    total_tax: Decimal = Decimal(0)
    traded_amount: Decimal = Decimal(0)


def _skipped_trade(
    sequence: int,
    signal: StrategySignal,
    skip_reason: TradeSkipReason,
) -> BacktestTrade:
    return BacktestTrade(
        sequence=sequence,
        signal_date=signal.signal_date,
        execution_date=None,
        action=signal.action,
        reason=signal.reason,
        quantity=0,
        price=None,
        gross_amount=Decimal(0),
        fee=Decimal(0),
        slippage=Decimal(0),
        tax=Decimal(0),
        skip_reason=skip_reason,
    )


def _execute_buy(
    inputs: BacktestInputs,
    account: _Account,
    sequence: int,
    signal: StrategySignal,
    fill: tuple[date, Decimal],
) -> BacktestTrade:
    execution_date, open_price = fill
    if account.shares > 0:
        return _skipped_trade(sequence, signal, TradeSkipReason.ALREADY_POSITIONED)
    rule_set = cost_rule_set_for(execution_date)
    quantity = int(account.cash / open_price)
    while quantity > 0:
        gross = open_price * quantity
        costs = trade_costs(rule_set, inputs.product_type, inputs.market, TradeSide.BUY, gross)
        if gross + costs.total <= account.cash:
            account.cash -= gross + costs.total
            account.shares += quantity
            account.total_fee += costs.fee
            account.total_slippage += costs.slippage
            account.total_tax += costs.tax
            account.traded_amount += gross
            return BacktestTrade(
                sequence=sequence,
                signal_date=signal.signal_date,
                execution_date=execution_date,
                action=signal.action,
                reason=signal.reason,
                quantity=quantity,
                price=open_price,
                gross_amount=gross,
                fee=costs.fee,
                slippage=costs.slippage,
                tax=costs.tax,
                skip_reason=None,
            )
        quantity -= 1
    return _skipped_trade(sequence, signal, TradeSkipReason.INSUFFICIENT_CASH)


def _execute_sell(
    inputs: BacktestInputs,
    account: _Account,
    sequence: int,
    signal: StrategySignal,
    fill: tuple[date, Decimal],
) -> BacktestTrade:
    execution_date, open_price = fill
    if account.shares == 0:
        return _skipped_trade(sequence, signal, TradeSkipReason.NO_POSITION)
    rule_set = cost_rule_set_for(execution_date)
    quantity = account.shares
    gross = open_price * quantity
    costs = trade_costs(rule_set, inputs.product_type, inputs.market, TradeSide.SELL, gross)
    account.cash += gross - costs.total
    account.shares = 0
    account.total_fee += costs.fee
    account.total_slippage += costs.slippage
    account.total_tax += costs.tax
    account.traded_amount += gross
    return BacktestTrade(
        sequence=sequence,
        signal_date=signal.signal_date,
        execution_date=execution_date,
        action=signal.action,
        reason=signal.reason,
        quantity=quantity,
        price=open_price,
        gross_amount=gross,
        fee=costs.fee,
        slippage=costs.slippage,
        tax=costs.tax,
        skip_reason=None,
    )


def _metrics(
    inputs: BacktestInputs,
    account: _Account,
    equity_curve: Sequence[EquityPoint],
    executed_count: int,
) -> BacktestMetrics:
    return backtest_metrics(
        MetricsInputs(
            initial_cash=inputs.initial_cash,
            benchmark_closes=inputs.benchmark_closes,
            total_fee=account.total_fee,
            total_slippage=account.total_slippage,
            total_tax=account.total_tax,
            traded_amount=account.traded_amount,
            executed_count=executed_count,
        ),
        equity_curve,
    )


def run_backtest(inputs: BacktestInputs, signal_fn: SignalFunction) -> BacktestResult:
    _validate_inputs(inputs)
    signals = _collect_signals(inputs, signal_fn)
    dates = inputs.trading_dates
    date_index = {trading_date: index for index, trading_date in enumerate(dates)}
    executions_by_date: dict[int, list[tuple[int, StrategySignal]]] = {}
    trades_by_sequence: dict[int, BacktestTrade] = {}
    for sequence, signal in enumerate(signals, start=1):
        execution_index = date_index[signal.signal_date] + 1
        if execution_index >= len(dates):
            trades_by_sequence[sequence] = _skipped_trade(
                sequence,
                signal,
                TradeSkipReason.WINDOW_END,
            )
            continue
        executions_by_date.setdefault(execution_index, []).append((sequence, signal))
    account = _Account(cash=inputs.initial_cash)
    equity_curve: list[EquityPoint] = []
    for index, trading_date in enumerate(dates):
        per_share = inputs.dividends.get(trading_date)
        if per_share is not None and account.shares > 0:
            account.cash += per_share * account.shares
        for sequence, signal in executions_by_date.get(index, ()):
            open_price = inputs.execution_bars[trading_date].open_price
            execute = _execute_buy if signal.action is SignalAction.BUY else _execute_sell
            trades_by_sequence[sequence] = execute(
                inputs,
                account,
                sequence,
                signal,
                (trading_date, open_price),
            )
        close_price = inputs.execution_bars[trading_date].close_price
        position_value = close_price * account.shares
        equity_curve.append(
            EquityPoint(
                trading_date=trading_date,
                cash=account.cash,
                position_value=position_value,
                nav=account.cash + position_value,
            )
        )
    trades = tuple(trades_by_sequence[sequence] for sequence in sorted(trades_by_sequence))
    executed_count = sum(1 for trade in trades if trade.skip_reason is None)
    return BacktestResult(
        trades=trades,
        equity_curve=tuple(equity_curve),
        metrics=_metrics(inputs, account, equity_curve, executed_count),
    )
