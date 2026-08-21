"""ML 순위 전략(ADR-0012, ML 신호 계약 §7).

이 전략의 위험은 성과가 아니라 해석이다. 학습 창과 겹치는 창으로 실행해 좋은 숫자가 나오면
그것이 표본 밖 성과로 오독된다. 그래서 겹침은 거부이고, 모델 부재도 거부다.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from auto_stock_trading.application.backtests.ml_signals import (
    ModelWindow,
    ml_rank_strategy,
)
from auto_stock_trading.domain.strategies.backtest import BacktestError, BacktestFailure
from auto_stock_trading.domain.strategies.composite_rank import CompositeParameters
from auto_stock_trading.domain.strategies.ranking import SymbolSeries
from auto_stock_trading.features.price_features import FEATURE_NAMES
from auto_stock_trading.ml.ridge import RidgeCoefficients

_START = date(2025, 1, 1)


def _model() -> RidgeCoefficients:
    return RidgeCoefficients(
        algorithm="ridge",
        feature_names=FEATURE_NAMES,
        coefficients=tuple(0.0 for _ in FEATURE_NAMES),
        intercept=0.0,
        alpha=1.0,
        seed=7,
    )


def _window(train_start: date, train_end: date) -> ModelWindow:
    return ModelWindow(train_start=train_start, train_end=train_end, embargo_days=20)


def _dates(count: int, start: date = _START) -> tuple[date, ...]:
    return tuple(start + timedelta(days=index) for index in range(count))


def _series(symbol: str, dates: tuple[date, ...]) -> SymbolSeries:
    return SymbolSeries(
        symbol=symbol,
        closes={day: Decimal(1000 + index) for index, day in enumerate(dates)},
    )


def test_a_backtest_window_overlapping_the_training_window_is_refused() -> None:
    dates = _dates(120)
    strategy = ml_rank_strategy(
        CompositeParameters(lookback_days=5, holdings=2),
        model=_model(),
        window=_window(dates[0], dates[60]),
        features={},
    )

    with pytest.raises(BacktestError) as error:
        _ = strategy.source.plan((dates[80],), (_series("000100", dates),), dates)

    assert error.value.failure is BacktestFailure.TRAIN_WINDOW_OVERLAP


def test_a_window_starting_after_the_embargo_is_accepted() -> None:
    dates = _dates(200)
    # 학습 종료 이후 엠바고 20거래일이 지난 시점부터가 표본 밖이다.
    strategy = ml_rank_strategy(
        CompositeParameters(lookback_days=5, holdings=2),
        model=_model(),
        window=_window(dates[0], dates[60]),
        features={
            "000100": {dates[120]: dict.fromkeys(FEATURE_NAMES, 0.0)},
        },
    )

    plan = strategy.source.plan((dates[120],), (_series("000100", dates),), dates)

    assert len(plan.rebalances) == 1
    assert [item.symbol for item in plan.rebalances[0].selected] == ["000100"]


def test_the_strategy_identity_names_the_model_and_feature_version() -> None:
    strategy = ml_rank_strategy(
        CompositeParameters(lookback_days=5, holdings=2),
        model=_model(),
        window=_window(_START, _START + timedelta(days=60)),
        features={},
    )

    assert strategy.name == "ml-rank"
    assert strategy.signal_method == "ml_rank"
    assert "features-1" in strategy.parameters_json
    assert "ridge" in strategy.parameters_json


def test_a_symbol_without_features_on_the_signal_date_is_not_a_candidate() -> None:
    dates = _dates(200)
    strategy = ml_rank_strategy(
        CompositeParameters(lookback_days=5, holdings=5),
        model=_model(),
        window=_window(dates[0], dates[60]),
        features={
            "000100": {dates[120]: dict.fromkeys(FEATURE_NAMES, 0.0)},
            # 000200은 그 날짜 특징이 없다 -> 후보 아님
            "000200": {dates[119]: dict.fromkeys(FEATURE_NAMES, 0.0)},
        },
    )

    plan = strategy.source.plan(
        (dates[120],),
        (_series("000100", dates), _series("000200", dates)),
        dates,
    )

    assert [item.symbol for item in plan.rebalances[0].selected] == ["000100"]


def test_higher_predictions_rank_first() -> None:
    dates = _dates(200)
    model = RidgeCoefficients(
        algorithm="ridge",
        feature_names=FEATURE_NAMES,
        # 첫 특징에만 양의 가중치를 준다.
        coefficients=tuple(1.0 if name == FEATURE_NAMES[0] else 0.0 for name in FEATURE_NAMES),
        intercept=0.0,
        alpha=1.0,
        seed=7,
    )

    def features(value: float) -> dict[str, float]:
        return {name: (value if name == FEATURE_NAMES[0] else 0.0) for name in FEATURE_NAMES}

    strategy = ml_rank_strategy(
        CompositeParameters(lookback_days=5, holdings=2),
        model=model,
        window=_window(dates[0], dates[60]),
        features={
            "000100": {dates[120]: features(0.1)},
            "000200": {dates[120]: features(0.9)},
            "000300": {dates[120]: features(0.5)},
        },
    )

    plan = strategy.source.plan(
        (dates[120],),
        tuple(_series(symbol, dates) for symbol in ("000100", "000200", "000300")),
        dates,
    )

    assert [item.symbol for item in plan.rebalances[0].selected] == ["000200", "000300"]


def test_a_round_without_any_candidate_produces_no_rebalance() -> None:
    dates = _dates(200)
    strategy = ml_rank_strategy(
        CompositeParameters(lookback_days=5, holdings=2),
        model=_model(),
        window=_window(dates[0], dates[60]),
        features={},
    )

    with pytest.raises(BacktestError) as error:
        _ = strategy.source.plan((dates[120],), (_series("000100", dates),), dates)

    assert error.value.failure is BacktestFailure.NO_SIGNAL_CANDIDATE
