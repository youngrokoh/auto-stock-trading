"""워크포워드 분할(ML 신호 계약 §시점 정합과 워크포워드). 순수 함수다.

엠바고가 이 모듈의 존재 이유다. 학습 표본의 라벨은 학습 종료일 + 목표 창까지의 미래를 본다.
검증을 학습 종료 바로 다음부터 잡으면 검증 초반이 학습과 같은 미래를 공유해 표본 밖 성과가
과대평가된다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from auto_stock_trading.features.targets import TARGET_HORIZON_DAYS

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

DEFAULT_MIN_TRAIN_DAYS: Final = 250
DEFAULT_EMBARGO_DAYS: Final = TARGET_HORIZON_DAYS
DEFAULT_VALID_DAYS: Final = 60


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    index: int
    train_start: date
    train_end: date
    valid_start: date
    valid_end: date


def walk_forward_folds(
    trading_dates: Sequence[date],
    *,
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    valid_days: int = DEFAULT_VALID_DAYS,
) -> tuple[WalkForwardFold, ...]:
    """확장창 구간 목록. 학습 시작은 고정이고 종료가 검증 길이만큼 전진한다."""
    if min_train_days < 1 or valid_days < 1:
        message = "min_train_days and valid_days must be positive"
        raise ValueError(message)
    if embargo_days < TARGET_HORIZON_DAYS:
        message = (
            f"embargo_days must be at least the target horizon ({TARGET_HORIZON_DAYS}); "
            "a shorter embargo leaks training labels into validation"
        )
        raise ValueError(message)
    dates = tuple(trading_dates)
    folds: list[WalkForwardFold] = []
    train_end_index = min_train_days - 1
    while True:
        valid_start_index = train_end_index + embargo_days + 1
        valid_end_index = valid_start_index + valid_days - 1
        if valid_end_index >= len(dates):
            break
        folds.append(
            WalkForwardFold(
                index=len(folds) + 1,
                train_start=dates[0],
                train_end=dates[train_end_index],
                valid_start=dates[valid_start_index],
                valid_end=dates[valid_end_index],
            )
        )
        train_end_index += valid_days
    return tuple(folds)
