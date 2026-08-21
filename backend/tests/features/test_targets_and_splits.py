"""목표 생성과 워크포워드 분할(ML 신호 계약 §목표, §시점 정합과 워크포워드).

엠바고가 이 계약의 핵심이다. 학습 라벨이 학습 종료일 +20까지의 미래를 보므로, 검증을 학습
종료일 바로 다음부터 잡으면 검증 초반이 학습과 같은 미래를 공유해 성능이 과대평가된다.
"""

from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest

from auto_stock_trading.features.splits import WalkForwardFold, walk_forward_folds
from auto_stock_trading.features.targets import (
    TARGET_HORIZON_DAYS,
    cross_sectional_ranks,
    excess_return,
)

_START = date(2024, 1, 1)


def _dates(count: int) -> tuple[date, ...]:
    return tuple(_START + timedelta(days=index) for index in range(count))


def _closes(values: dict[int, str], dates: tuple[date, ...]) -> dict[date, Decimal]:
    return {dates[index]: Decimal(value) for index, value in values.items()}


def test_target_horizon_is_twenty_trading_days() -> None:
    assert TARGET_HORIZON_DAYS == 20


def test_excess_return_is_symbol_return_minus_benchmark_return() -> None:
    dates = _dates(30)
    closes = _closes({0: "1000", 20: "1100"}, dates)
    benchmark = _closes({0: "2000", 20: "2100"}, dates)

    value = excess_return(closes, benchmark, dates, dates[0])

    # 종목 +10%, 벤치마크 +5% -> 초과 +5%
    assert value == Decimal("0.05")


def test_a_signal_date_without_a_full_horizon_has_no_target() -> None:
    dates = _dates(21)
    closes = _closes({0: "1000", 20: "1100"}, dates)
    benchmark = _closes({0: "2000", 20: "2100"}, dates)

    assert excess_return(closes, benchmark, dates, dates[1]) is None


def test_a_missing_future_close_has_no_target() -> None:
    dates = _dates(30)
    closes = _closes({0: "1000"}, dates)
    benchmark = _closes({0: "2000", 20: "2100"}, dates)

    assert excess_return(closes, benchmark, dates, dates[0]) is None


def test_cross_sectional_ranks_are_percentiles_with_the_best_at_one() -> None:
    ranks = cross_sectional_ranks(
        {
            "000100": Decimal("0.05"),
            "000200": Decimal("-0.02"),
            "000300": Decimal("0.01"),
        }
    )

    assert ranks == {
        "000100": Decimal(1),
        "000300": Decimal("0.5"),
        "000200": Decimal(0),
    }


def test_tied_excess_returns_share_a_percentile() -> None:
    ranks = cross_sectional_ranks(
        {"000100": Decimal("0.03"), "000200": Decimal("0.03"), "000300": Decimal("-0.01")}
    )

    assert ranks["000100"] == ranks["000200"]
    assert ranks["000300"] == Decimal(0)


def test_a_single_candidate_has_no_cross_section() -> None:
    """한 종목만 있으면 상대 순위가 의미를 갖지 못하므로 표본을 만들지 않는다."""
    assert cross_sectional_ranks({"000100": Decimal("0.05")}) == {}


def test_folds_leave_an_embargo_between_training_and_validation() -> None:
    dates = _dates(400)

    folds = walk_forward_folds(dates, min_train_days=250, embargo_days=20, valid_days=60)

    assert folds
    first = folds[0]
    assert first == WalkForwardFold(
        index=1,
        train_start=dates[0],
        train_end=dates[249],
        valid_start=dates[270],
        valid_end=dates[329],
    )
    # 학습 종료와 검증 시작 사이에 정확히 20거래일이 비어 있다.
    assert dates.index(first.valid_start) - dates.index(first.train_end) == 21


def test_folds_expand_the_training_window_and_advance_by_the_validation_length() -> None:
    dates = _dates(400)

    folds = walk_forward_folds(dates, min_train_days=250, embargo_days=20, valid_days=60)

    assert [fold.index for fold in folds] == list(range(1, len(folds) + 1))
    assert all(fold.train_start == dates[0] for fold in folds)
    for previous, current in pairwise(folds):
        assert dates.index(current.train_end) - dates.index(previous.train_end) == 60


def test_a_fold_whose_validation_window_runs_past_the_data_is_not_created() -> None:
    dates = _dates(320)

    folds = walk_forward_folds(dates, min_train_days=250, embargo_days=20, valid_days=60)

    # 250 + 20 + 60 = 330 > 320 이므로 만들 수 있는 구간이 없다.
    assert folds == ()


def test_zero_embargo_is_refused_because_it_leaks_the_training_labels() -> None:
    dates = _dates(400)

    with pytest.raises(ValueError, match="embargo"):
        _ = walk_forward_folds(dates, min_train_days=250, embargo_days=0, valid_days=60)
