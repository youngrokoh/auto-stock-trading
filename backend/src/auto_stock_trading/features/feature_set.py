"""특징 집합 버전(ML 신호 계약 §특징).

특징을 하나라도 바꾸면 버전을 올리고 이전 모델은 이전 버전으로 남는다. 모델 행에 버전이 저장돼
있어 어떤 집합으로 학습한 모델인지 나중에 구분된다.
"""

from typing import Final

from auto_stock_trading.features.fundamental_features import FUNDAMENTAL_FEATURE_NAMES
from auto_stock_trading.features.price_features import FEATURE_NAMES as PRICE_FEATURE_NAMES

FEATURE_SET_PRICE: Final = "features-1"
FEATURE_SET_WITH_FUNDAMENTALS: Final = "features-2"

_SETS: Final = {
    FEATURE_SET_PRICE: PRICE_FEATURE_NAMES,
    FEATURE_SET_WITH_FUNDAMENTALS: PRICE_FEATURE_NAMES + FUNDAMENTAL_FEATURE_NAMES,
}


def feature_names(version: str) -> tuple[str, ...]:
    """버전의 특징 이름 목록. 순서가 학습 행렬의 열 순서다."""
    names = _SETS.get(version)
    if names is None:
        message = f"unknown feature set: {version!r}"
        raise ValueError(message)
    return names


def uses_fundamentals(version: str) -> bool:
    return version == FEATURE_SET_WITH_FUNDAMENTALS
