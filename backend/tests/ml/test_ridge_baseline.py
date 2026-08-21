"""Ridge 기준선 학습과 평가(ML 신호 계약 §모델, §평가 지표).

기준선의 목적은 성과가 아니라 검증이다. 특징이 신호를 담는지, 학습이 재현되는지, 산출물이
안전한 포맷으로 왕복하는지를 먼저 고정한다.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from auto_stock_trading.ml.evaluation import fold_metrics
from auto_stock_trading.ml.ridge import (
    RIDGE_ALGORITHM,
    RidgeCoefficients,
    predict,
    train_ridge,
)
from auto_stock_trading.ml.samples import TrainingSample

_START = date(2024, 1, 1)


def _sample(index: int, first: float, second: float, target: float) -> TrainingSample:
    return TrainingSample(
        symbol=f"{index % 5:06d}",
        signal_date=_START + timedelta(days=index),
        features=(first, second),
        target=target,
    )


def _linear_samples(count: int) -> tuple[TrainingSample, ...]:
    # target = 0.3 * first - 0.1 * second (+ 절편 0). 노이즈 없이 계수 회수를 확인한다.
    return tuple(
        _sample(
            index,
            first := (index % 11) / 10.0,
            second := (index % 7) / 10.0,
            0.3 * first - 0.1 * second,
        )
        for index in range(count)
    )


def test_training_recovers_a_known_linear_relation() -> None:
    model = train_ridge(_linear_samples(120), ("first", "second"), alpha=1e-8, seed=7)

    assert model.algorithm == RIDGE_ALGORITHM
    assert model.feature_names == ("first", "second")
    assert model.coefficients[0] == pytest.approx(0.3, abs=1e-4)
    assert model.coefficients[1] == pytest.approx(-0.1, abs=1e-4)


def test_training_is_reproducible_for_the_same_input_and_seed() -> None:
    samples = _linear_samples(120)

    first = train_ridge(samples, ("first", "second"), alpha=0.5, seed=7)
    second = train_ridge(samples, ("first", "second"), alpha=0.5, seed=7)

    assert first.to_json() == second.to_json()


def test_the_artifact_round_trips_through_its_native_json() -> None:
    model = train_ridge(_linear_samples(120), ("first", "second"), alpha=0.5, seed=7)

    restored = RidgeCoefficients.from_json(model.to_json())

    assert restored == model
    assert predict(restored, (0.4, 0.2)) == pytest.approx(predict(model, (0.4, 0.2)))


def test_a_feature_count_mismatch_is_rejected() -> None:
    model = train_ridge(_linear_samples(120), ("first", "second"), alpha=0.5, seed=7)

    with pytest.raises(ValueError, match="feature"):
        _ = predict(model, (0.4,))


def test_training_refuses_a_sample_set_below_the_minimum() -> None:
    with pytest.raises(ValueError, match="samples"):
        _ = train_ridge(_linear_samples(3), ("first", "second"), alpha=0.5, seed=7, min_samples=100)


def test_fold_metrics_report_rank_correlation_and_top_k_excess() -> None:
    # 예측이 실제 순위와 완전히 일치하는 하루
    predictions = {"000100": 0.9, "000200": 0.5, "000300": 0.1}
    actual = {
        "000100": Decimal("0.10"),
        "000200": Decimal("0.02"),
        "000300": Decimal("-0.05"),
    }

    metrics = fold_metrics(((_START, predictions, actual),), top_k=1)

    assert metrics["rank_ic"] == pytest.approx(1.0)
    assert metrics["top_k_excess"] == pytest.approx(0.10)
    assert metrics["hit_rate"] == pytest.approx(1.0)
    assert metrics["sample_count"] == 3


def test_fold_metrics_report_a_negative_ic_when_the_ranking_is_inverted() -> None:
    predictions = {"000100": 0.1, "000200": 0.5, "000300": 0.9}
    actual = {
        "000100": Decimal("0.10"),
        "000200": Decimal("0.02"),
        "000300": Decimal("-0.05"),
    }

    metrics = fold_metrics(((_START, predictions, actual),), top_k=1)

    assert metrics["rank_ic"] == pytest.approx(-1.0)
    assert metrics["top_k_excess"] == pytest.approx(-0.05)
    assert metrics["hit_rate"] == pytest.approx(0.0)


def test_a_day_without_a_cross_section_is_skipped_by_the_metrics() -> None:
    """한 종목만 있는 날은 순위 상관이 정의되지 않으므로 지표에서 뺀다."""
    single = (_START, {"000100": 0.9}, {"000100": Decimal("0.10")})
    pair = (
        _START + timedelta(days=1),
        {"000100": 0.9, "000200": 0.1},
        {"000100": Decimal("0.10"), "000200": Decimal("-0.01")},
    )

    metrics = fold_metrics((single, pair), top_k=1)

    assert metrics["sample_count"] == 2
    assert metrics["rank_ic"] == pytest.approx(1.0)
