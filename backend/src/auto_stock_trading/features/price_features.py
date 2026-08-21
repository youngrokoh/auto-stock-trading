"""ML 특징 계산(ML 신호 계약 §특징). 순수 함수이며 저장·조회를 하지 않는다.

보조지표는 규칙형 전략과 같은 함수를 호출한다. ML용 정의를 새로 만들면 화면·백테스트·모델이
서로 다른 숫자를 쓰게 된다.

전체 시계열을 받아 날짜별 행을 돌려주는 형태를 쓴다. 접두 시계열로 다시 계산해도 같은 값이
나오는지 검사할 수 있어야 하기 때문이다(계약 검증 1).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.strategies.indicators import atr, bollinger, macd, rsi, sma

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from auto_stock_trading.domain.strategies.indicators import IndicatorSeries

FEATURE_VERSION: Final = "features-1"

_RSI_PERIOD: Final = 14
_ATR_PERIOD: Final = 14
_MACD_FAST: Final = 12
_MACD_SLOW: Final = 26
_MACD_SIGNAL: Final = 9
_BOLLINGER_PERIOD: Final = 20
_BOLLINGER_MULTIPLIER: Final = Decimal(2)
_LONG_WINDOW: Final = 60
_MEAN_WINDOW: Final = 20
_SHORT_WINDOW: Final = 5
_SLOPE_SPAN: Final = 5

FEATURE_NAMES: Final = (
    "ret_1",
    "ret_5",
    "ret_20",
    "ret_60",
    "vol_20",
    "vol_60",
    "body",
    "upper_wick",
    "lower_wick",
    "gap",
    "dist_sma5",
    "dist_sma20",
    "dist_sma60",
    "slope_sma20",
    "rsi_14",
    "macd_hist_norm",
    "atr_14_norm",
    "bb_percent_b",
    "volume_ratio_20",
    "value_ratio_20",
    "mkt_ret_20",
    "mkt_vol_20",
    "rel_ret_20",
)


@dataclass(frozen=True, slots=True)
class FeatureBar:
    """특징 계산에 필요한 확정 일봉 필드."""

    trading_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    trading_value: Decimal


@dataclass(frozen=True, slots=True)
class FeatureRow:
    trading_date: date
    values: Mapping[str, Decimal]


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _return(values: Sequence[Decimal], index: int, span: int) -> Decimal | None:
    if index - span < 0:
        return None
    base = values[index - span]
    if base <= 0:
        return None
    return values[index] / base - 1


def _volatility(returns: Sequence[Decimal | None], index: int, window: int) -> Decimal | None:
    start = index - window + 1
    if start < 0:
        return None
    sample = returns[start : index + 1]
    if any(value is None for value in sample):
        return None
    present = [value for value in sample if value is not None]
    mean = sum(present, Decimal(0)) / window
    variance = sum(((value - mean) ** 2 for value in present), Decimal(0)) / window
    return variance.sqrt()


def _mean(values: Sequence[Decimal], index: int, window: int) -> Decimal | None:
    start = index - window + 1
    if start < 0:
        return None
    return sum(values[start : index + 1], Decimal(0)) / window


def _distance(close: Decimal, average: Decimal | None) -> Decimal | None:
    if average is None or average <= 0:
        return None
    return close / average - 1


def _percent_b(
    close: Decimal,
    upper: Decimal | None,
    lower: Decimal | None,
) -> Decimal | None:
    if upper is None or lower is None:
        return None
    width = upper - lower
    if width <= 0:
        return None
    return (close - lower) / width


@dataclass(frozen=True, slots=True)
class _Series:
    closes: tuple[Decimal, ...]
    volumes: tuple[Decimal, ...]
    values: tuple[Decimal, ...]
    returns: tuple[Decimal | None, ...]
    sma5: IndicatorSeries
    sma20: IndicatorSeries
    sma60: IndicatorSeries
    rsi14: IndicatorSeries
    macd_hist: IndicatorSeries
    atr14: IndicatorSeries
    bb_upper: IndicatorSeries
    bb_lower: IndicatorSeries


def _prepare(bars: Sequence[FeatureBar]) -> _Series:
    closes = tuple(bar.close_price for bar in bars)
    bands = bollinger(closes, _BOLLINGER_PERIOD, _BOLLINGER_MULTIPLIER)
    return _Series(
        closes=closes,
        volumes=tuple(Decimal(bar.volume) for bar in bars),
        values=tuple(bar.trading_value for bar in bars),
        returns=tuple(_return(closes, index, 1) for index in range(len(closes))),
        sma5=sma(closes, _SHORT_WINDOW),
        sma20=sma(closes, _MEAN_WINDOW),
        sma60=sma(closes, _LONG_WINDOW),
        rsi14=rsi(closes, _RSI_PERIOD),
        macd_hist=macd(closes, _MACD_FAST, _MACD_SLOW, _MACD_SIGNAL).histogram,
        atr14=atr(
            tuple(bar.high_price for bar in bars),
            tuple(bar.low_price for bar in bars),
            closes,
            _ATR_PERIOD,
        ),
        bb_upper=bands.upper,
        bb_lower=bands.lower,
    )


def _candle_features(bar: FeatureBar, previous_close: Decimal) -> dict[str, Decimal | None]:
    body_top = max(bar.open_price, bar.close_price)
    body_bottom = min(bar.open_price, bar.close_price)
    return {
        "body": _ratio(bar.close_price - bar.open_price, bar.open_price),
        "upper_wick": _ratio(bar.high_price - body_top, bar.open_price),
        "lower_wick": _ratio(body_bottom - bar.low_price, bar.open_price),
        "gap": _ratio(bar.open_price - previous_close, previous_close),
    }


def _market_features(
    benchmark: Sequence[Decimal],
    index: int,
    symbol_ret_20: Decimal | None,
) -> dict[str, Decimal | None]:
    market_ret = _return(benchmark, index, _MEAN_WINDOW)
    market_returns = tuple(_return(benchmark, position, 1) for position in range(index + 1))
    return {
        "mkt_ret_20": market_ret,
        "mkt_vol_20": _volatility(market_returns, index, _MEAN_WINDOW),
        "rel_ret_20": (
            None if market_ret is None or symbol_ret_20 is None else symbol_ret_20 - market_ret
        ),
    }


def _row_values(
    bars: Sequence[FeatureBar],
    series: _Series,
    benchmark: Sequence[Decimal],
    index: int,
) -> dict[str, Decimal | None]:
    bar = bars[index]
    close = bar.close_price
    ret_20 = _return(series.closes, index, _MEAN_WINDOW)
    sma20_now = series.sma20[index]
    sma20_past = series.sma20[index - _SLOPE_SPAN] if index >= _SLOPE_SPAN else None
    macd_hist = series.macd_hist[index]
    atr_value = series.atr14[index]
    volume_mean = _mean(series.volumes, index, _MEAN_WINDOW)
    value_mean = _mean(series.values, index, _MEAN_WINDOW)
    values: dict[str, Decimal | None] = {
        "ret_1": series.returns[index],
        "ret_5": _return(series.closes, index, _SHORT_WINDOW),
        "ret_20": ret_20,
        "ret_60": _return(series.closes, index, _LONG_WINDOW),
        "vol_20": _volatility(series.returns, index, _MEAN_WINDOW),
        "vol_60": _volatility(series.returns, index, _LONG_WINDOW),
        "dist_sma5": _distance(close, series.sma5[index]),
        "dist_sma20": _distance(close, sma20_now),
        "dist_sma60": _distance(close, series.sma60[index]),
        "slope_sma20": (
            None
            if sma20_now is None or sma20_past is None or sma20_past <= 0
            else sma20_now / sma20_past - 1
        ),
        "rsi_14": series.rsi14[index],
        "macd_hist_norm": None if macd_hist is None else _ratio(macd_hist, close),
        "atr_14_norm": None if atr_value is None else _ratio(atr_value, close),
        "bb_percent_b": _percent_b(close, series.bb_upper[index], series.bb_lower[index]),
        "volume_ratio_20": (
            None if volume_mean is None else _ratio(series.volumes[index], volume_mean)
        ),
        "value_ratio_20": (
            None if value_mean is None else _ratio(series.values[index], value_mean)
        ),
    }
    values.update(_candle_features(bar, series.closes[index - 1]))
    values.update(_market_features(benchmark, index, ret_20))
    return values


def feature_rows(
    bars: Sequence[FeatureBar],
    benchmark_closes: Sequence[Decimal],
) -> tuple[FeatureRow, ...]:
    """날짜별 특징 행. 창이 모자라거나 값이 하나라도 없으면 그 행을 만들지 않는다."""
    if len(bars) != len(benchmark_closes):
        message = "benchmark_closes must align with bars"
        raise ValueError(message)
    if not bars:
        return ()
    series = _prepare(bars)
    rows: list[FeatureRow] = []
    for index in range(1, len(bars)):
        values = _row_values(bars, series, benchmark_closes, index)
        present = {name: value for name in FEATURE_NAMES if (value := values[name]) is not None}
        if len(present) != len(FEATURE_NAMES):
            continue
        rows.append(FeatureRow(trading_date=bars[index].trading_date, values=present))
    return tuple(rows)
