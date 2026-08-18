from decimal import Decimal

import pytest

from auto_stock_trading.domain.strategies.indicators import (
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
)

_ONE_TO_FIVE = tuple(Decimal(value) for value in (1, 2, 3, 4, 5))


def _quantized(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.000000000001"))


def test_sma_returns_window_average_after_warmup() -> None:
    assert sma(_ONE_TO_FIVE, 3) == (None, None, Decimal(2), Decimal(3), Decimal(4))


def test_sma_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError, match="period"):
        _ = sma(_ONE_TO_FIVE, 0)


def test_ema_seeds_with_simple_average_then_smooths() -> None:
    values = ema(_ONE_TO_FIVE, 3)
    assert [_quantized(value) for value in values] == [
        None,
        None,
        _quantized(Decimal(2)),
        _quantized(Decimal(3)),
        _quantized(Decimal(4)),
    ]


def test_rsi_uses_wilder_smoothing() -> None:
    values = rsi(tuple(Decimal(value) for value in (10, 11, 10, 11)), 2)
    assert [_quantized(value) for value in values] == [
        None,
        None,
        _quantized(Decimal(50)),
        _quantized(Decimal(75)),
    ]


def test_rsi_handles_all_gains_and_all_losses() -> None:
    ascending = rsi(tuple(Decimal(value) for value in (1, 2, 3, 4)), 3)
    descending = rsi(tuple(Decimal(value) for value in (4, 3, 2, 1)), 3)
    flat = rsi(tuple(Decimal(value) for value in (5, 5, 5, 5)), 3)
    assert ascending[3] == Decimal(100)
    assert descending[3] == Decimal(0)
    assert flat[3] == Decimal(50)


def test_rsi_returns_all_none_when_series_too_short() -> None:
    assert rsi(tuple(Decimal(value) for value in (1, 2, 3)), 3) == (None, None, None)


def test_macd_matches_hand_computed_series() -> None:
    result = macd(_ONE_TO_FIVE, 2, 3, 2)
    assert [_quantized(value) for value in result.macd] == [
        None,
        None,
        _quantized(Decimal("0.5")),
        _quantized(Decimal("0.5")),
        _quantized(Decimal("0.5")),
    ]
    assert [_quantized(value) for value in result.signal] == [
        None,
        None,
        None,
        _quantized(Decimal("0.5")),
        _quantized(Decimal("0.5")),
    ]
    assert [_quantized(value) for value in result.histogram] == [
        None,
        None,
        None,
        _quantized(Decimal(0)),
        _quantized(Decimal(0)),
    ]


def test_atr_seeds_with_true_range_average_then_smooths() -> None:
    highs = tuple(Decimal(value) for value in (12, 13, 15))
    lows = tuple(Decimal(value) for value in (8, 10, 11))
    closes = tuple(Decimal(value) for value in (10, 12, 14))
    values = atr(highs, lows, closes, 2)
    assert [_quantized(value) for value in values] == [
        None,
        _quantized(Decimal("3.5")),
        _quantized(Decimal("3.75")),
    ]


def test_atr_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="length"):
        _ = atr((Decimal(1),), (Decimal(1), Decimal(2)), (Decimal(1),), 2)


def test_bollinger_uses_population_deviation() -> None:
    result = bollinger(_ONE_TO_FIVE, 3, Decimal(2))
    assert result.middle == (None, None, Decimal(2), Decimal(3), Decimal(4))
    assert _quantized(result.upper[2]) == _quantized(Decimal("3.632993161855452"))
    assert _quantized(result.lower[2]) == _quantized(Decimal("0.367006838144548"))


def test_indicators_are_scale_invariant_for_signals() -> None:
    scale = Decimal("0.9979577032531667")
    scaled = tuple(value * scale for value in _ONE_TO_FIVE)
    original_rsi = rsi(_ONE_TO_FIVE, 3)
    scaled_rsi = rsi(scaled, 3)
    assert [_quantized(value) for value in original_rsi] == [
        _quantized(value) for value in scaled_rsi
    ]
    original_sma = sma(_ONE_TO_FIVE, 2)
    scaled_sma = sma(scaled, 2)
    for original, adjusted in zip(original_sma, scaled_sma, strict=True):
        if original is None or adjusted is None:
            assert original == adjusted
            continue
        assert _quantized(original * scale) == _quantized(adjusted)
