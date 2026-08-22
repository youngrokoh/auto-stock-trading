# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportAny=false
"""LightGBM 경계(ML 신호 계약 §모델).

이 파일은 외부 라이브러리와 닿는 유일한 지점이다. `lightgbm`과 `numpy`는 타입 스텁이 없거나
부분적으로 `Any`를 노출하므로 `typeCheckingMode = "all"` 예외를 **이 파일에만** 둔다. 경계 밖으로는
타입이 확정된 값만 내보낸다.

산출물은 LightGBM 자체 텍스트 포맷이다. Python pickle은 임의 코드 실행 위험 때문에 쓰지 않는다
(기술 스택 §6.1).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final

import lightgbm as lgb
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from auto_stock_trading.ml.samples import TrainingSample

LIGHTGBM_ALGORITHM: Final = "lightgbm"
DEFAULT_BOOST_ROUNDS: Final = 300
_IMPORTANCE_TYPE: Final = "gain"


def default_parameters(*, seed: int) -> dict[str, object]:
    """연구 기본값. 결정적 학습을 위해 스레드 하나와 `deterministic`을 고정한다.

    스레드를 늘리면 히스토그램 축약 순서가 달라져 같은 입력에서도 산출물이 흔들린다. 재현성이
    계약 요건이므로 속도보다 결정성을 택한다.
    """
    return {
        "objective": "regression",
        "metric": "l2",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 1.0,
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
    }


@final
@dataclass(frozen=True, slots=True)
class LightGbmModel:
    algorithm: str
    feature_names: tuple[str, ...]
    _booster: lgb.Booster

    def predict(self, features: Sequence[float]) -> float:
        if len(features) != len(self.feature_names):
            message = f"expected {len(self.feature_names)} feature values, got {len(features)}"
            raise ValueError(message)
        matrix = np.array([list(features)], dtype=np.float64)
        # `predict`의 선언 반환형이 희소행렬을 포함하므로 조밀 배열로 확정한 뒤 값을 꺼낸다.
        values = np.asarray(self._booster.predict(matrix), dtype=np.float64)
        return float(values[0])

    def predict_many(self, rows: Sequence[Sequence[float]]) -> tuple[float, ...]:
        """여러 행을 한 번에 예측한다. 회차마다 200종목을 부르는 경로가 있어 필요하다."""
        if not rows:
            return ()
        for row in rows:
            if len(row) != len(self.feature_names):
                message = f"expected {len(self.feature_names)} feature values, got {len(row)}"
                raise ValueError(message)
        matrix = np.array([list(row) for row in rows], dtype=np.float64)
        values = np.asarray(self._booster.predict(matrix), dtype=np.float64)
        return tuple(float(value) for value in values)

    def to_artifact(self) -> str:
        return str(self._booster.model_to_string())

    def importances(self) -> dict[str, float]:
        raw = np.asarray(
            self._booster.feature_importance(importance_type=_IMPORTANCE_TYPE),
            dtype=np.float64,
        )
        return {
            name: float(value) for name, value in zip(self.feature_names, raw.tolist(), strict=True)
        }

    @classmethod
    def from_artifact(cls, artifact: str, feature_names: Sequence[str]) -> LightGbmModel:
        booster = lgb.Booster(model_str=artifact)
        return cls(
            algorithm=LIGHTGBM_ALGORITHM,
            feature_names=tuple(feature_names),
            _booster=booster,
        )


@dataclass(frozen=True, slots=True)
class LightGbmSettings:
    """학습 설정 묶음. 인자를 늘리는 대신 한 값으로 넘겨 호출부가 읽히게 한다."""

    parameters: Mapping[str, object]
    seed: int
    min_samples: int = 0
    boost_rounds: int = DEFAULT_BOOST_ROUNDS


def train_lightgbm(
    samples: Sequence[TrainingSample],
    feature_names: Sequence[str],
    settings: LightGbmSettings,
) -> LightGbmModel:
    """표본을 시그널일·종목 순으로 정렬해 학습한다. 정렬이 없으면 결과가 입력 순서에 의존한다."""
    if len(samples) < settings.min_samples:
        message = f"need at least {settings.min_samples} training samples, got {len(samples)}"
        raise ValueError(message)
    if not samples:
        message = "need at least 1 training sample, got 0"
        raise ValueError(message)
    names = tuple(feature_names)
    ordered = sorted(samples, key=lambda sample: (sample.signal_date, sample.symbol))
    for sample in ordered:
        if len(sample.features) != len(names):
            message = f"sample feature count {len(sample.features)} does not match {len(names)}"
            raise ValueError(message)
    matrix = np.array([list(sample.features) for sample in ordered], dtype=np.float64)
    targets = np.array([sample.target for sample in ordered], dtype=np.float64)
    booster_params = {**dict(settings.parameters), "seed": settings.seed}
    dataset = lgb.Dataset(
        matrix,
        label=targets,
        feature_name=list(names),
        params={"verbose": -1},
    )
    booster = lgb.train(booster_params, dataset, num_boost_round=settings.boost_rounds)
    return LightGbmModel(
        algorithm=LIGHTGBM_ALGORITHM,
        feature_names=names,
        _booster=booster,
    )
