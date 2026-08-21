"""ML 특징 계산(ML 신호 계약 §특징).

가장 위험한 것은 미래정보 누출이다. 특징이 T 이후 행을 조금이라도 참조하면 모델 성능은
좋아지지만 실전에서는 재현되지 않는다. 그래서 접두 재계산 동일성을 고정한다.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from auto_stock_trading.features.price_features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    FeatureBar,
    feature_rows,
)

_START = date(2024, 1, 1)


def _bar(index: int, close: str, *, volume: int = 1000) -> FeatureBar:
    price = Decimal(close)
    return FeatureBar(
        trading_date=_START + timedelta(days=index),
        open_price=price - Decimal(2),
        high_price=price + Decimal(3),
        low_price=price - Decimal(4),
        close_price=price,
        volume=volume,
        trading_value=price * volume,
    )


def _series(count: int) -> tuple[FeatureBar, ...]:
    # 완만한 상승과 주기적 흔들림을 섞어 지표가 상수로 굳지 않게 한다.
    return tuple(
        _bar(index, str(1000 + index * 3 + (index % 7) * 5), volume=1000 + (index % 5) * 120)
        for index in range(count)
    )


def _benchmark(count: int) -> tuple[Decimal, ...]:
    return tuple(Decimal(2000 + index * 2 + (index % 3)) for index in range(count))


def test_feature_names_are_stable_and_versioned() -> None:
    assert FEATURE_VERSION == "features-1"
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert FEATURE_NAMES[0] == "ret_1"
    assert "rel_ret_20" in FEATURE_NAMES


def test_rows_start_only_when_every_feature_window_is_filled() -> None:
    bars = _series(80)
    rows = feature_rows(bars, _benchmark(80))

    assert rows
    # 가장 긴 창은 60거래일 수익률이라 61번째 봉부터 행이 생긴다.
    assert rows[0].trading_date == bars[60].trading_date
    assert all(name in rows[0].values for name in FEATURE_NAMES)
    assert all(value is not None for value in rows[0].values.values())


def test_a_short_series_produces_no_rows_instead_of_filling_gaps() -> None:
    assert feature_rows(_series(40), _benchmark(40)) == ()


def test_prefix_recomputation_gives_the_same_row() -> None:
    """계약 검증 1. 접두 시계열만으로 같은 값이 나와야 미래정보 누출이 없다."""
    bars = _series(90)
    benchmark = _benchmark(90)
    full = feature_rows(bars, benchmark)

    for cutoff in (70, 80, 89):
        prefix = feature_rows(bars[: cutoff + 1], benchmark[: cutoff + 1])
        assert prefix[-1].trading_date == bars[cutoff].trading_date
        matching = next(row for row in full if row.trading_date == bars[cutoff].trading_date)
        assert prefix[-1].values == matching.values


def test_returns_and_candle_features_match_hand_computation() -> None:
    bars = _series(70)
    row = feature_rows(bars, _benchmark(70))[0]
    latest = bars[60]

    expected_ret_1 = latest.close_price / bars[59].close_price - 1
    expected_body = (latest.close_price - latest.open_price) / latest.open_price
    expected_gap = (latest.open_price - bars[59].close_price) / bars[59].close_price

    assert row.values["ret_1"] == expected_ret_1
    assert row.values["body"] == expected_body
    assert row.values["gap"] == expected_gap


def test_market_features_come_from_the_benchmark_series() -> None:
    bars = _series(70)
    benchmark = _benchmark(70)
    row = feature_rows(bars, benchmark)[0]

    expected = benchmark[60] / benchmark[40] - 1
    assert row.values["mkt_ret_20"] == expected
    assert row.values["rel_ret_20"] == row.values["ret_20"] - expected


def test_mismatched_benchmark_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="benchmark"):
        _ = feature_rows(_series(70), _benchmark(69))


def test_a_zero_price_row_is_dropped_instead_of_dividing_by_zero() -> None:
    bars = list(_series(70))
    broken = bars[60]
    bars[60] = FeatureBar(
        trading_date=broken.trading_date,
        open_price=Decimal(0),
        high_price=broken.high_price,
        low_price=broken.low_price,
        close_price=broken.close_price,
        volume=broken.volume,
        trading_value=broken.trading_value,
    )

    rows = feature_rows(tuple(bars), _benchmark(70))

    assert all(row.trading_date != broken.trading_date for row in rows)
