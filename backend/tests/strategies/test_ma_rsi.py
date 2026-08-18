from datetime import date, timedelta
from decimal import Decimal

import pytest

from auto_stock_trading.domain.strategies.ma_rsi import (
    InvalidStrategyParametersError,
    MaRsiParameters,
    SignalAction,
    SignalReason,
    ma_rsi_signals,
)

_PARAMETERS = MaRsiParameters(
    short_period=2,
    long_period=3,
    rsi_period=2,
    rsi_overbought=Decimal(90),
)
_CLOSES = tuple(Decimal(value) for value in (10, 9, 8, 9, 12, 13, 12, 9))
_DATES = tuple(date(2026, 8, 3) + timedelta(days=index) for index in range(len(_CLOSES)))


def test_signals_cover_cross_and_overbought_rules() -> None:
    signals = ma_rsi_signals(_DATES, _CLOSES, _PARAMETERS)
    assert [(signal.signal_date, signal.action, signal.reason) for signal in signals] == [
        (_DATES[4], SignalAction.BUY, SignalReason.GOLDEN_CROSS),
        (_DATES[5], SignalAction.SELL, SignalReason.RSI_OVERBOUGHT),
        (_DATES[7], SignalAction.SELL, SignalReason.DEAD_CROSS),
    ]


def test_no_signals_before_warmup_completes() -> None:
    signals = ma_rsi_signals(_DATES[:4], _CLOSES[:4], _PARAMETERS)
    assert signals == ()


def test_overbought_filter_suppresses_buy_on_golden_cross() -> None:
    parameters = MaRsiParameters(
        short_period=2,
        long_period=3,
        rsi_period=2,
        rsi_overbought=Decimal(80),
    )
    signals = ma_rsi_signals(_DATES, _CLOSES, parameters)
    assert [(signal.signal_date, signal.action) for signal in signals] == [
        (_DATES[4], SignalAction.SELL),
        (_DATES[5], SignalAction.SELL),
        (_DATES[7], SignalAction.SELL),
    ]


def test_parameters_require_short_below_long() -> None:
    with pytest.raises(InvalidStrategyParametersError):
        _ = MaRsiParameters(
            short_period=3,
            long_period=3,
            rsi_period=2,
            rsi_overbought=Decimal(70),
        )


def test_signals_reject_mismatched_series_lengths() -> None:
    with pytest.raises(ValueError, match="length"):
        _ = ma_rsi_signals(_DATES[:3], _CLOSES, _PARAMETERS)
