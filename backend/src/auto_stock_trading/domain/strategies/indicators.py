from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

type IndicatorSeries = tuple[Decimal | None, ...]

_HUNDRED: Final = Decimal(100)
_NEUTRAL_RSI: Final = Decimal(50)


@dataclass(frozen=True, slots=True)
class MacdSeries:
    macd: IndicatorSeries
    signal: IndicatorSeries
    histogram: IndicatorSeries


@dataclass(frozen=True, slots=True)
class BollingerSeries:
    upper: IndicatorSeries
    middle: IndicatorSeries
    lower: IndicatorSeries


def _require_period(period: int) -> None:
    if period < 1:
        msg = "period must be a positive integer"
        raise ValueError(msg)


def sma(values: Sequence[Decimal], period: int) -> IndicatorSeries:
    _require_period(period)
    result: list[Decimal | None] = [None] * len(values)
    window_sum = Decimal(0)
    for index, value in enumerate(values):
        window_sum += value
        if index >= period:
            window_sum -= values[index - period]
        if index >= period - 1:
            result[index] = window_sum / period
    return tuple(result)


def _ema_from_optional(values: Sequence[Decimal | None], period: int) -> IndicatorSeries:
    _require_period(period)
    result: list[Decimal | None] = [None] * len(values)
    smoothing = Decimal(2) / (period + 1)
    previous: Decimal | None = None
    seed_sum = Decimal(0)
    seed_count = 0
    for index, value in enumerate(values):
        if value is None:
            continue
        if previous is None:
            seed_sum += value
            seed_count += 1
            if seed_count == period:
                previous = seed_sum / period
                result[index] = previous
            continue
        previous = previous + smoothing * (value - previous)
        result[index] = previous
    return tuple(result)


def ema(values: Sequence[Decimal], period: int) -> IndicatorSeries:
    return _ema_from_optional(tuple(values), period)


def rsi(values: Sequence[Decimal], period: int) -> IndicatorSeries:
    _require_period(period)
    result: list[Decimal | None] = [None] * len(values)
    if len(values) <= period:
        return tuple(result)
    average_gain = Decimal(0)
    average_loss = Decimal(0)
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, Decimal(0))
        loss = max(-change, Decimal(0))
        if index <= period:
            average_gain += gain / period
            average_loss += loss / period
            if index < period:
                continue
        else:
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        if average_loss == 0:
            result[index] = _NEUTRAL_RSI if average_gain == 0 else _HUNDRED
        else:
            result[index] = _HUNDRED - _HUNDRED / (1 + average_gain / average_loss)
    return tuple(result)


def macd(
    values: Sequence[Decimal],
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> MacdSeries:
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    line = tuple(
        None if fast_value is None or slow_value is None else fast_value - slow_value
        for fast_value, slow_value in zip(fast, slow, strict=True)
    )
    signal = _ema_from_optional(line, signal_period)
    histogram = tuple(
        None if line_value is None or signal_value is None else line_value - signal_value
        for line_value, signal_value in zip(line, signal, strict=True)
    )
    return MacdSeries(macd=line, signal=signal, histogram=histogram)


def atr(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    period: int,
) -> IndicatorSeries:
    _require_period(period)
    if len(highs) != len(lows) or len(highs) != len(closes):
        msg = "highs, lows and closes must share the same length"
        raise ValueError(msg)
    result: list[Decimal | None] = [None] * len(highs)
    previous_atr: Decimal | None = None
    seed_sum = Decimal(0)
    for index in range(len(highs)):
        true_range = highs[index] - lows[index]
        if index > 0:
            previous_close = closes[index - 1]
            true_range = max(
                true_range,
                abs(highs[index] - previous_close),
                abs(lows[index] - previous_close),
            )
        if previous_atr is None:
            seed_sum += true_range
            if index == period - 1:
                previous_atr = seed_sum / period
                result[index] = previous_atr
            continue
        previous_atr = (previous_atr * (period - 1) + true_range) / period
        result[index] = previous_atr
    return tuple(result)


def bollinger(values: Sequence[Decimal], period: int, multiplier: Decimal) -> BollingerSeries:
    middle = sma(values, period)
    upper: list[Decimal | None] = [None] * len(values)
    lower: list[Decimal | None] = [None] * len(values)
    for index, mean in enumerate(middle):
        if mean is None:
            continue
        window = values[index - period + 1 : index + 1]
        variance = sum(((value - mean) ** 2 for value in window), Decimal(0)) / period
        deviation = variance.sqrt()
        upper[index] = mean + multiplier * deviation
        lower[index] = mean - multiplier * deviation
    return BollingerSeries(upper=tuple(upper), middle=middle, lower=tuple(lower))
