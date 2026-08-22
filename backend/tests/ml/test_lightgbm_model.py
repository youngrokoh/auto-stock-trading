"""LightGBM 경계(ML 신호 계약 §모델).

계약이 요구하는 세 가지를 고정한다: 산출물은 네이티브 텍스트(pickle 금지), 같은 입력·시드면
같은 산출물, 텍스트 왕복 후 예측이 같다.
"""

from datetime import date, timedelta

import pytest

from auto_stock_trading.ml.lightgbm_model import (
    LIGHTGBM_ALGORITHM,
    LightGbmModel,
    LightGbmSettings,
    default_parameters,
    train_lightgbm,
)
from auto_stock_trading.ml.ridge import predict as ridge_predict
from auto_stock_trading.ml.ridge import train_ridge
from auto_stock_trading.ml.samples import TrainingSample

_START = date(2024, 1, 1)
_NAMES = ("first", "second")


def _settings() -> LightGbmSettings:
    return LightGbmSettings(parameters=default_parameters(seed=7), seed=7)


def _samples(count: int) -> tuple[TrainingSample, ...]:
    # 구간에 따라 기울기가 바뀌는 관계. 선형 모델로는 잡기 어렵고 트리는 잡을 수 있다.
    def target(first: float, second: float) -> float:
        return (0.9 * first if first > 0.5 else 0.1 * first) - 0.2 * second

    return tuple(
        TrainingSample(
            symbol=f"{index % 7:06d}",
            signal_date=_START + timedelta(days=index),
            features=(first := (index % 23) / 22.0, second := (index % 11) / 10.0),
            target=target(first, second),
            excess=target(first, second) / 10,
        )
        for index in range(count)
    )


def test_training_produces_a_native_text_artifact() -> None:
    model = train_lightgbm(_samples(600), _NAMES, _settings())

    assert model.algorithm == LIGHTGBM_ALGORITHM
    assert model.feature_names == _NAMES
    artifact = model.to_artifact()
    # LightGBM 자체 텍스트 포맷이어야 한다. pickle 바이트가 아니다.
    assert artifact.startswith("tree")
    assert "objective=regression" in artifact


def test_training_is_reproducible_for_the_same_input_and_seed() -> None:
    samples = _samples(600)

    first = train_lightgbm(samples, _NAMES, _settings())
    second = train_lightgbm(samples, _NAMES, _settings())

    assert first.to_artifact() == second.to_artifact()


def test_the_artifact_round_trips_and_keeps_predictions() -> None:
    model = train_lightgbm(_samples(600), _NAMES, _settings())

    restored = LightGbmModel.from_artifact(model.to_artifact(), _NAMES)

    for point in ((0.2, 0.3), (0.8, 0.1), (0.55, 0.9)):
        assert restored.predict(point) == pytest.approx(model.predict(point), abs=1e-12)


def test_a_feature_count_mismatch_is_rejected() -> None:
    model = train_lightgbm(_samples(600), _NAMES, _settings())

    with pytest.raises(ValueError, match="feature"):
        _ = model.predict((0.4,))


def test_training_refuses_a_sample_set_below_the_minimum() -> None:
    with pytest.raises(ValueError, match="samples"):
        _ = train_lightgbm(
            _samples(10),
            _NAMES,
            LightGbmSettings(parameters=default_parameters(seed=7), seed=7, min_samples=100),
        )


def test_importances_cover_every_feature() -> None:
    model = train_lightgbm(_samples(600), _NAMES, _settings())

    importances = model.importances()

    assert set(importances) == set(_NAMES)
    assert all(value >= 0.0 for value in importances.values())


def test_the_tree_model_beats_a_linear_fit_on_a_piecewise_relation() -> None:
    """트리를 쓰는 이유를 고정한다. 구간별 기울기를 선형 한 장으로는 맞출 수 없다."""
    samples = _samples(600)
    tree = train_lightgbm(samples, _NAMES, _settings())
    linear = train_ridge(samples, _NAMES, alpha=1e-6, seed=7)

    def error(predictor: object) -> float:
        total = 0.0
        for sample in samples:
            value = (
                tree.predict(sample.features)
                if predictor is tree
                else ridge_predict(linear, sample.features)
            )
            total += (value - sample.target) ** 2
        return total / len(samples)

    assert error(tree) < error(linear)
