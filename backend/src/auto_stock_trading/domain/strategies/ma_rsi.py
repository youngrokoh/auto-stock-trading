from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

from auto_stock_trading.domain.strategies.indicators import rsi, sma

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal

STRATEGY_NAME: Final = "ma-rsi"
STRATEGY_VERSION: Final = "1"


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"


class SignalReason(StrEnum):
    GOLDEN_CROSS = "golden_cross"
    DEAD_CROSS = "dead_cross"
    RSI_OVERBOUGHT = "rsi_overbought"


@dataclass(frozen=True, slots=True)
class InvalidStrategyParametersError(Exception):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class MaRsiParameters:
    short_period: int
    long_period: int
    rsi_period: int
    rsi_overbought: Decimal

    def __post_init__(self) -> None:
        if self.short_period < 1 or self.rsi_period < 1:
            msg = "indicator periods must be positive integers"
            raise InvalidStrategyParametersError(msg)
        if self.short_period >= self.long_period:
            msg = "short_period must be smaller than long_period"
            raise InvalidStrategyParametersError(msg)


@dataclass(frozen=True, slots=True)
class StrategySignal:
    signal_date: date
    action: SignalAction
    reason: SignalReason


def ma_rsi_signals(
    dates: Sequence[date],
    closes: Sequence[Decimal],
    parameters: MaRsiParameters,
) -> tuple[StrategySignal, ...]:
    if len(dates) != len(closes):
        msg = "dates and closes must share the same length"
        raise ValueError(msg)
    short_series = sma(closes, parameters.short_period)
    long_series = sma(closes, parameters.long_period)
    rsi_series = rsi(closes, parameters.rsi_period)
    signals: list[StrategySignal] = []
    for index in range(1, len(closes)):
        short_today = short_series[index]
        long_today = long_series[index]
        short_prior = short_series[index - 1]
        long_prior = long_series[index - 1]
        rsi_today = rsi_series[index]
        if (
            short_today is None
            or long_today is None
            or short_prior is None
            or long_prior is None
            or rsi_today is None
        ):
            continue
        dead_cross = short_prior >= long_prior and short_today < long_today
        golden_cross = short_prior <= long_prior and short_today > long_today
        if dead_cross or rsi_today >= parameters.rsi_overbought:
            reason = SignalReason.DEAD_CROSS if dead_cross else SignalReason.RSI_OVERBOUGHT
            signals.append(StrategySignal(dates[index], SignalAction.SELL, reason))
        elif golden_cross:
            signals.append(
                StrategySignal(dates[index], SignalAction.BUY, SignalReason.GOLDEN_CROSS)
            )
    return tuple(signals)
