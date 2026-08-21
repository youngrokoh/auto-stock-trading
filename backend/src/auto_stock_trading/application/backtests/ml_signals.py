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
from auto_stock_trading.features.price_features import FEATURE_NAMES, FEATURE_VERSION
from auto_stock_trading.ml.ridge import predict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from auto_stock_trading.domain.strategies.composite_rank import CompositeParameters
    from auto_stock_trading.domain.strategies.ranking import SymbolSeries
    from auto_stock_trading.ml.ridge import RidgeCoefficients

ML_STRATEGY_NAME: Final = "ml-rank"
ML_STRATEGY_VERSION: Final = "1"
ML_SIGNAL_METHOD: Final = "ml_rank"

type SymbolFeatures = Mapping[str, Mapping[date, Mapping[str, float]]]


@dataclass(frozen=True, slots=True)
class ModelWindow:
    """모델이 학습에 사용한 창과 엠바고. 표본 밖 판정의 근거다."""

    train_start: date
    train_end: date
    embargo_days: int


@final
@dataclass(frozen=True, slots=True)
class _MlSource:
    parameters: CompositeParameters
    model: RidgeCoefficients
    window: ModelWindow
    features: SymbolFeatures

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
            selected = self._selected(signal_date, series, settings.holdings)
            if not selected:
                continue
            rebalances.append(Rebalance(signal_date=signal_date, selected=selected))
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
        dates = tuple(calendar)
        try:
            train_end_index = dates.index(self.window.train_end)
        except ValueError:
            # 학습 종료일이 창 안에 없다면 창이 학습 이후이거나 이전이다. 날짜로 비교한다.
            if min(signal_dates) > self.window.train_end:
                return
            raise BacktestError(
                BacktestFailure.TRAIN_WINDOW_OVERLAP,
                f"signal dates reach into the training window ending {self.window.train_end}",
            ) from None
        first_out_of_sample = train_end_index + self.window.embargo_days + 1
        if first_out_of_sample >= len(dates):
            raise BacktestError(
                BacktestFailure.TRAIN_WINDOW_OVERLAP,
                "the window ends before the embargo after training completes",
            )
        boundary = dates[first_out_of_sample]
        if min(signal_dates) < boundary:
            raise BacktestError(
                BacktestFailure.TRAIN_WINDOW_OVERLAP,
                f"signal dates start at {min(signal_dates)} before the embargo ends {boundary}",
            )

    def _selected(
        self,
        signal_date: date,
        series: Sequence[SymbolSeries],
        holdings: int,
    ) -> tuple[RankedSymbol, ...]:
        scored: list[tuple[str, float]] = []
        for item in series:
            values = self.features.get(item.symbol, {}).get(signal_date)
            if values is None or item.closes.get(signal_date) is None:
                continue
            if any(name not in values for name in FEATURE_NAMES):
                continue
            scored.append(
                (item.symbol, predict(self.model, tuple(values[name] for name in FEATURE_NAMES)))
            )
        scored.sort(key=lambda entry: (-entry[1], entry[0]))
        return tuple(
            RankedSymbol(symbol=symbol, score=quantized_score(_as_decimal(score)))
            for symbol, score in scored[:holdings]
        )


def _as_decimal(value: float) -> Decimal:
    """예측값을 점수 타입으로 옮긴다. `repr`을 쓰면 부동소수 표현이 그대로 보존된다."""
    return Decimal(repr(value))


def ml_rank_strategy(
    parameters: CompositeParameters,
    *,
    model: RidgeCoefficients,
    window: ModelWindow,
    features: SymbolFeatures,
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
                "feature_version": FEATURE_VERSION,
                "holdings": settings.holdings,
                "lookback_days": settings.lookback_days,
                "train_end": window.train_end.isoformat(),
                "train_start": window.train_start.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        source=_MlSource(settings, model, window, features),
    )
