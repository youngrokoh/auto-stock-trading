"""Ridge 기준선(ML 신호 계약 §모델).

기준선의 목적은 성과가 아니라 검증이다. 특징이 신호를 담는지, 학습이 재현되는지를 먼저 본다.
산출물은 계수 JSON으로만 저장한다 — Python pickle은 임의 코드 실행 위험 때문에 쓰지 않는다.

Ridge는 닫힌 해가 있어 표준 라이브러리만으로 정확히 푼다(`(X'X + alpha*I)w = X'y`, 절편은
중심화로 처리). 특징이 23개라 정규방정식이 23x23이고 가우스 소거로 충분하다. 외부 수치
라이브러리를 쓰지 않는 이유는 `typeCheckingMode = "all"` 게이트다 — `scikit-learn`은 타입 스텁이
없고 `numpy`도 부분적으로 `Any`를 노출한다. 주력 모델(LightGBM)을 도입할 때는 경계 모듈로
격리하고 그 파일에만 예외를 둔다.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from auto_stock_trading.ml.samples import TrainingSample

RIDGE_ALGORITHM: Final = "ridge"
DEFAULT_ALPHA: Final = 1.0
DEFAULT_MIN_SAMPLES: Final = 1_000
_ARTIFACT_FORMAT: Final = "ridge-coefficients-1"
_SINGULAR_TOLERANCE: Final = 1e-12


@dataclass(frozen=True, slots=True)
class RidgeCoefficients:
    algorithm: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    alpha: float
    seed: int

    def to_artifact(self) -> str:
        """공통 경계용 이름. 내용은 `to_json`과 같다."""
        return self.to_json()

    def importances(self) -> dict[str, float]:
        """선형 모델의 중요도는 계수 절대값이다. 특징이 정규화돼 있어 비교가 성립한다."""
        return {
            name: abs(weight)
            for name, weight in zip(self.feature_names, self.coefficients, strict=True)
        }

    def predict(self, features: Sequence[float]) -> float:
        return predict(self, features)

    def to_json(self) -> str:
        """계수만 담은 안전한 네이티브 포맷. 키 순서를 고정해 재현 비교가 가능하다."""
        return json.dumps(
            {
                "algorithm": self.algorithm,
                "alpha": self.alpha,
                "coefficients": list(self.coefficients),
                "feature_names": list(self.feature_names),
                "format": _ARTIFACT_FORMAT,
                "intercept": self.intercept,
                "seed": self.seed,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> RidgeCoefficients:
        """저장된 계수를 되읽는다. 형식 검증은 pydantic 모델이 맡는다."""
        artifact = _RidgeArtifact.model_validate_json(payload)
        if artifact.format != _ARTIFACT_FORMAT:
            message = f"unsupported ridge artifact format: {artifact.format!r}"
            raise ValueError(message)
        if len(artifact.feature_names) != len(artifact.coefficients):
            message = "ridge artifact feature_names and coefficients must have equal length"
            raise ValueError(message)
        return cls(
            algorithm=artifact.algorithm,
            feature_names=artifact.feature_names,
            coefficients=artifact.coefficients,
            intercept=artifact.intercept,
            alpha=artifact.alpha,
            seed=artifact.seed,
        )


class _RidgeArtifact(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    format: str
    algorithm: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    alpha: float
    seed: int


def train_ridge(
    samples: Sequence[TrainingSample],
    feature_names: Sequence[str],
    *,
    alpha: float = DEFAULT_ALPHA,
    seed: int = 0,
    min_samples: int = 0,
) -> RidgeCoefficients:
    """표본을 시그널일·종목 순으로 정렬해 학습한다. 정렬이 없으면 결과가 입력 순서에 의존한다."""
    if len(samples) < min_samples:
        message = f"need at least {min_samples} training samples, got {len(samples)}"
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
    weights, intercept = _solve(
        [sample.features for sample in ordered],
        [sample.target for sample in ordered],
        alpha,
    )
    return RidgeCoefficients(
        algorithm=RIDGE_ALGORITHM,
        feature_names=names,
        coefficients=tuple(weights),
        intercept=intercept,
        alpha=alpha,
        seed=seed,
    )


def _solve(
    rows: Sequence[Sequence[float]],
    targets: Sequence[float],
    alpha: float,
) -> tuple[list[float], float]:
    """중심화 후 정규방정식을 푼다. 절편은 벌점을 받지 않는다(표준 Ridge 정의)."""
    count = len(rows)
    width = len(rows[0])
    feature_means = [sum(row[column] for row in rows) / count for column in range(width)]
    target_mean = sum(targets) / count
    gram = [[0.0] * width for _ in range(width)]
    moment = [0.0] * width
    for row, target in zip(rows, targets, strict=True):
        centered = [row[column] - feature_means[column] for column in range(width)]
        residual = target - target_mean
        for left in range(width):
            value = centered[left]
            moment[left] += value * residual
            gram_row = gram[left]
            for right in range(left, width):
                gram_row[right] += value * centered[right]
    for left in range(width):
        gram[left][left] += alpha
        for right in range(left):
            gram[left][right] = gram[right][left]
    weights = _gaussian_solve(gram, moment)
    intercept = target_mean - sum(
        mean * weight for mean, weight in zip(feature_means, weights, strict=True)
    )
    return weights, intercept


def _gaussian_solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """부분 피벗 가우스 소거. 정규방정식이 특이하면 추측하지 않고 실패한다."""
    size = len(vector)
    augmented = [[*matrix[row], vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < _SINGULAR_TOLERANCE:
            message = "ridge normal equations are singular; check for constant features"
            raise ValueError(message)
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        for index in range(column, size + 1):
            augmented[column][index] /= divisor
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            for index in range(column, size + 1):
                augmented[row][index] -= factor * augmented[column][index]
    return [augmented[row][size] for row in range(size)]


def predict(model: RidgeCoefficients, features: Sequence[float]) -> float:
    if len(features) != len(model.coefficients):
        message = f"expected {len(model.coefficients)} feature values, got {len(features)}"
        raise ValueError(message)
    total = model.intercept
    for weight, value in zip(model.coefficients, features, strict=True):
        total += weight * value
    return total
