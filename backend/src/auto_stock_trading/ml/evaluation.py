"""워크포워드 구간 지표(ML 신호 계약 §평가 지표). 순수 함수다.

구간 평균만 보고하면 한 시기에 성과가 몰린 것을 놓치므로, 구간별 값을 그대로 저장할 수 있게
날짜별 계산을 분리해 둔다.
"""

from decimal import Decimal
from math import sqrt
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

type DailyOutcome = tuple[date, Mapping[str, float], Mapping[str, Decimal]]

_MIN_CROSS_SECTION: Final = 2
DEFAULT_TOP_K: Final = 10


def _ranks(values: Sequence[float]) -> list[float]:
    """동점은 평균 순위를 나눠 갖는다(스피어만 상관의 표준 처리)."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        stop = position
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[position]]:
            stop += 1
        shared = (position + stop) / 2 + 1
        for index in order[position : stop + 1]:
            ranks[index] = shared
        position = stop + 1
    return ranks


def spearman(predicted: Sequence[float], actual: Sequence[float]) -> float | None:
    if len(predicted) != len(actual):
        message = "predicted and actual must share the same length"
        raise ValueError(message)
    if len(predicted) < _MIN_CROSS_SECTION:
        return None
    left = _ranks(predicted)
    right = _ranks(actual)
    count = len(left)
    mean_left = sum(left, 0.0) / count
    mean_right = sum(right, 0.0) / count
    covariance = 0.0
    variance_left = 0.0
    variance_right = 0.0
    for a, b in zip(left, right, strict=True):
        left_deviation = a - mean_left
        right_deviation = b - mean_right
        covariance += left_deviation * right_deviation
        variance_left += left_deviation * left_deviation
        variance_right += right_deviation * right_deviation
    if variance_left <= 0.0 or variance_right <= 0.0:
        return None
    return covariance / sqrt(variance_left * variance_right)


def fold_metrics(
    outcomes: Sequence[DailyOutcome],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, float]:
    """구간 지표. 횡단면이 없는 날은 통째로 제외한다.

    `sample_count`는 지표를 실제로 계산한 표본 수다. 제외한 날의 표본을 세면 지표가 더 많은
    데이터에 근거한 것처럼 보인다.
    """
    if top_k < 1:
        message = "top_k must be positive"
        raise ValueError(message)
    correlations: list[float] = []
    top_excess: list[float] = []
    hits = 0
    scored_days = 0
    samples = 0
    for _, predictions, actual in outcomes:
        shared = sorted(set(predictions) & set(actual))
        if len(shared) < _MIN_CROSS_SECTION:
            continue
        samples += len(shared)
        correlation = spearman(
            [predictions[symbol] for symbol in shared],
            [float(actual[symbol]) for symbol in shared],
        )
        if correlation is not None:
            correlations.append(correlation)
        chosen = sorted(shared, key=lambda symbol: (-predictions[symbol], symbol))[:top_k]
        average = sum(float(actual[symbol]) for symbol in chosen) / len(chosen)
        top_excess.append(average)
        scored_days += 1
        if average > 0:
            hits += 1
    return {
        "rank_ic": sum(correlations) / len(correlations) if correlations else 0.0,
        "top_k_excess": sum(top_excess) / len(top_excess) if top_excess else 0.0,
        "hit_rate": hits / scored_days if scored_days else 0.0,
        "sample_count": float(samples),
    }
