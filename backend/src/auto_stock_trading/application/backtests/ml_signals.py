"""ML 순위 전략 조립(ADR-0012, ML 신호 계약 §7).

이 모듈은 저장된 모델로 추론만 한다. 학습하지 않는다 — 실행마다 모델이 달라지면 재현성이
깨지고, 창 겹침을 구조적으로 막을 수 없다.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final

from auto_stock_trading.application.backtests.portfolio_runner import (
    SignalPlan,
    StrategySpec,
)
from auto_stock_trading.domain.strategies.backtest import BacktestError, BacktestFailure
from auto_stock_trading.domain.strategies.ranking import (
    RankedSymbol,
    Rebalance,
    quantized_score,
)
from auto_stock_trading.features.feature_set import FEATURE_SET_PRICE, feature_names

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from auto_stock_trading.domain.strategies.composite_rank import CompositeParameters
    from auto_stock_trading.domain.strategies.ranking import SymbolSeries
    from auto_stock_trading.ml.models import PredictiveModel

ML_STRATEGY_NAME: Final = "ml-rank"
ML_STRATEGY_VERSION: Final = "1"
ML_SIGNAL_METHOD: Final = "ml_rank"
# 교체 임계: 보유 중이면 상위 2K까지 유지한다. 폭은 사전에 고정하고 탐색하지 않는다
# (ML 신호 계약 §예측 안정화, 2026-08-22 사용자 승인).
RETAINED_BAND_MULTIPLE: Final = 2

type SymbolFeatures = Mapping[str, Mapping[date, Mapping[str, float]]]


@dataclass(frozen=True, slots=True)
class ModelWindow:
    """모델이 학습에 사용한 창과 표본 밖 시작일. 표본 밖 판정의 근거다.

    `out_of_sample_start`는 학습 시점 달력으로 계산해 저장한 값이다. 백테스트 창의 달력만으로는
    학습 창과의 거래일 간격을 셀 수 없으므로, 창이 학습 창 밖에 있을 때 이 값이 유일한 근거다.
    """

    train_start: date
    train_end: date
    embargo_days: int
    out_of_sample_start: date | None = None


@final
@dataclass(frozen=True, slots=True)
class _MlSource:
    parameters: CompositeParameters
    model: PredictiveModel
    window: ModelWindow
    features: SymbolFeatures
    # 특징 이름은 모델이 학습한 집합을 따라간다. 하드코딩하면 집합이 다른 모델에서
    # 열 개수가 어긋난다(2026-08-22 실측 결함).
    feature_version: str = FEATURE_SET_PRICE

    def plan(
        self,
        signal_dates: Sequence[date],
        series: Sequence[SymbolSeries],
        trading_dates: Sequence[date],
    ) -> SignalPlan:
        settings = self.parameters.validated()
        calendar = tuple(trading_dates)
        self._reject_overlap(calendar, signal_dates)
        index_of = {day: index for index, day in enumerate(calendar)}
        rebalances: list[Rebalance] = []
        for signal_date in signal_dates:
            position = index_of.get(signal_date)
            if position is None or position - settings.lookback_days < 0:
                continue
            ranked = self._ranked(signal_date, series)
            if not ranked:
                continue
            selected = tuple(ranked[: settings.holdings])
            band = settings.holdings * RETAINED_BAND_MULTIPLE
            retained = tuple(item.symbol for item in ranked[settings.holdings : band])
            rebalances.append(
                Rebalance(
                    signal_date=signal_date,
                    selected=selected,
                    retained=retained,
                )
            )
        if not rebalances:
            raise BacktestError(
                BacktestFailure.NO_SIGNAL_CANDIDATE,
                "no rebalance had a symbol with features on the signal date",
            )
        return SignalPlan(rebalances=tuple(rebalances))

    def _reject_overlap(self, calendar: Sequence[date], signal_dates: Sequence[date]) -> None:
        """엠바고가 끝나기 전의 시그널일이 하나라도 있으면 실행 자체를 거부한다."""
        if not signal_dates:
            return
        boundary = self._boundary(calendar)
        if boundary is None:
            raise BacktestError(
                BacktestFailure.TRAIN_WINDOW_OVERLAP,
                "the model has no recorded out-of-sample start and the window cannot prove one",
            )
        if min(signal_dates) < boundary:
            raise BacktestError(
                BacktestFailure.TRAIN_WINDOW_OVERLAP,
                f"signal dates start at {min(signal_dates)} before the embargo ends {boundary}",
            )

    def _boundary(self, calendar: Sequence[date]) -> date | None:
        """표본 밖 시작일. 저장값이 있으면 그것을 쓰고, 없으면 창 달력에서 센다."""
        if self.window.out_of_sample_start is not None:
            return self.window.out_of_sample_start
        dates = tuple(calendar)
        try:
            train_end_index = dates.index(self.window.train_end)
        except ValueError:
            # 학습 종료일이 창 안에 없으면 사이 거래일을 셀 수 없다. 추측하지 않는다.
            return None
        target = train_end_index + self.window.embargo_days + 1
        if target >= len(dates):
            return None
        return dates[target]

    def _ranked(
        self,
        signal_date: date,
        series: Sequence[SymbolSeries],
    ) -> tuple[RankedSymbol, ...]:
        """예측이 높은 순으로 정렬한 후보 전체. 동점은 종목코드 오름차순이다."""
        scored: list[tuple[str, float]] = []
        for item in series:
            values = self.features.get(item.symbol, {}).get(signal_date)
            if values is None or item.closes.get(signal_date) is None:
                continue
            names = feature_names(self.feature_version)
            if any(name not in values for name in names):
                continue
            scored.append(
                (
                    item.symbol,
                    self.model.predict(tuple(values[name] for name in names)),
                )
            )
        scored.sort(key=lambda entry: (-entry[1], entry[0]))
        return tuple(
            RankedSymbol(symbol=symbol, score=quantized_score(_as_decimal(score)))
            for symbol, score in scored
        )


def _as_decimal(value: float) -> Decimal:
    """예측값을 점수 타입으로 옮긴다. `repr`을 쓰면 부동소수 표현이 그대로 보존된다."""
    return Decimal(repr(value))


def ml_rank_strategy(
    parameters: CompositeParameters,
    *,
    model: PredictiveModel,
    window: ModelWindow,
    features: SymbolFeatures,
    feature_version: str = FEATURE_SET_PRICE,
) -> StrategySpec:
    settings = parameters.validated()
    return StrategySpec(
        name=ML_STRATEGY_NAME,
        version=ML_STRATEGY_VERSION,
        signal_method=ML_SIGNAL_METHOD,
        holdings=settings.holdings,
        parameters_json=json.dumps(
            {
                "algorithm": model.algorithm,
                "embargo_days": window.embargo_days,
                "feature_version": feature_version,
                "holdings": settings.holdings,
                "lookback_days": settings.lookback_days,
                "train_end": window.train_end.isoformat(),
                "train_start": window.train_start.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        source=_MlSource(settings, model, window, features, feature_version),
    )
