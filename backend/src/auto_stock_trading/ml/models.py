"""학습된 모델의 공통 경계(ML 신호 계약 §모델).

전략과 학습 파이프라인은 알고리즘을 몰라야 한다. 예측과 산출물만 알면 Ridge든 LightGBM이든
같은 경로로 흐른다.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence


class PredictiveModel(Protocol):
    @property
    def algorithm(self) -> str: ...

    @property
    def feature_names(self) -> tuple[str, ...]: ...

    def predict(self, features: Sequence[float]) -> float: ...

    def to_artifact(self) -> str: ...

    def importances(self) -> dict[str, float]: ...
