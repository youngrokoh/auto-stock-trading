"""워크포워드 학습 유스케이스(ML 신호 계약 §시점 정합과 워크포워드, §저장).

학습 자체는 순수 함수가 하고, 이 층은 데이터 로드·구간 분할·구간별 평가·저장을 잇는다.
구간 지표는 구간마다 저장한다 — 평균만 남기면 한 시기에 성과가 몰린 것을 놓친다.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from auto_stock_trading.features.price_features import FEATURE_NAMES, FEATURE_VERSION
from auto_stock_trading.features.splits import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_MIN_TRAIN_DAYS,
    DEFAULT_VALID_DAYS,
    WalkForwardFold,
    walk_forward_folds,
)
from auto_stock_trading.features.targets import TARGET_HORIZON_DAYS, cross_sectional_ranks
from auto_stock_trading.ml.evaluation import fold_metrics
from auto_stock_trading.ml.lightgbm_model import (
    LIGHTGBM_ALGORITHM,
    LightGbmSettings,
    default_parameters,
    train_lightgbm,
)
from auto_stock_trading.ml.records import (
    FeatureImportanceRecord,
    ModelEvaluationRecord,
    ModelRecord,
)
from auto_stock_trading.ml.ridge import (
    DEFAULT_ALPHA,
    RIDGE_ALGORITHM,
    train_ridge,
)
from auto_stock_trading.ml.samples import TrainingSample

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.features.price_features import FeatureRow
    from auto_stock_trading.ml.models import PredictiveModel

TARGET_DEFINITION = "cross_sectional_rank_of_20d_excess_return"


class TrainingDataset(Protocol):
    async def trading_dates(self, start: date, end: date) -> tuple[date, ...]: ...

    async def universe_symbols(self) -> tuple[str, ...]: ...

    async def feature_rows(self, symbol: str) -> tuple[FeatureRow, ...]: ...

    async def targets(self, symbol: str) -> dict[date, Decimal]: ...

    async def bar_version_hash(self) -> str: ...

    async def close(self) -> None: ...


class ModelStore(Protocol):
    async def save_model(
        self,
        record: ModelRecord,
        evaluations: tuple[ModelEvaluationRecord, ...],
        importances: tuple[FeatureImportanceRecord, ...],
    ) -> UUID: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ModelTrainingRequest:
    name: str
    version: str
    range_start: date
    range_end: date
    algorithm: str = RIDGE_ALGORITHM
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS
    valid_days: int = DEFAULT_VALID_DAYS
    embargo_days: int = DEFAULT_EMBARGO_DAYS
    alpha: float = DEFAULT_ALPHA
    seed: int = 0
    min_train_samples: int = 1_000
    top_k: int = 10


@dataclass(frozen=True, slots=True)
class ModelTrainer:
    dataset: TrainingDataset
    store: ModelStore

    async def prepare(
        self,
        request: ModelTrainingRequest,
    ) -> tuple[tuple[WalkForwardFold, ...], tuple[TrainingSample, ...]]:
        """구간과 전체 표본을 만든다. 표본의 목표는 횡단면 순위이므로 날짜별로 함께 계산한다."""
        dates = await self.dataset.trading_dates(request.range_start, request.range_end)
        folds = walk_forward_folds(
            dates,
            min_train_days=request.min_train_days,
            embargo_days=request.embargo_days,
            valid_days=request.valid_days,
        )
        symbols = await self.dataset.universe_symbols()
        features: dict[str, dict[date, tuple[float, ...]]] = {}
        excess: dict[date, dict[str, Decimal]] = {}
        for symbol in symbols:
            rows = await self.dataset.feature_rows(symbol)
            features[symbol] = {
                row.trading_date: tuple(float(row.values[name]) for name in FEATURE_NAMES)
                for row in rows
            }
            for signal_date, value in (await self.dataset.targets(symbol)).items():
                excess.setdefault(signal_date, {})[symbol] = value
        samples: list[TrainingSample] = []
        for signal_date in sorted(excess):
            ranks = cross_sectional_ranks(excess[signal_date])
            for symbol, rank in sorted(ranks.items()):
                values = features.get(symbol, {}).get(signal_date)
                if values is None:
                    continue
                samples.append(
                    TrainingSample(
                        symbol=symbol,
                        signal_date=signal_date,
                        features=values,
                        target=float(rank),
                        excess=float(excess[signal_date][symbol]),
                    )
                )
        return folds, tuple(samples)

    async def run(self, request: ModelTrainingRequest, now: datetime) -> ModelRecord:
        folds, samples = await self.prepare(request)
        dates = await self.dataset.trading_dates(request.range_start, request.range_end)
        if not folds:
            message = "no walk-forward fold fits the requested window"
            raise ValueError(message)
        final_fold = folds[-1]
        training = tuple(sample for sample in samples if sample.signal_date <= final_fold.train_end)
        if len(training) < request.min_train_samples:
            message = (
                f"need at least {request.min_train_samples} training samples, got {len(training)}"
            )
            raise ValueError(message)
        model = _fit(training, request)
        evaluations = self._evaluate(folds, samples, request)
        record = ModelRecord(
            model_id=uuid4(),
            name=request.name,
            version=request.version,
            algorithm=model.algorithm,
            feature_version=FEATURE_VERSION,
            target_definition=TARGET_DEFINITION,
            train_start=final_fold.train_start,
            train_end=final_fold.train_end,
            embargo_days=request.embargo_days,
            horizon_days=TARGET_HORIZON_DAYS,
            out_of_sample_start=_out_of_sample_start(
                dates,
                final_fold.train_end,
                request.embargo_days,
            ),
            universe_size=len({sample.symbol for sample in samples}),
            train_sample_count=len(training),
            hyperparameters_json=_hyperparameters_json(request),
            seed=request.seed,
            artifact=model.to_artifact(),
            input_bar_version_hash=await self.dataset.bar_version_hash(),
            created_at=now,
        )
        _ = await self.store.save_model(record, evaluations, _importances(record.model_id, model))
        return record

    def _evaluate(
        self,
        folds: tuple[WalkForwardFold, ...],
        samples: tuple[TrainingSample, ...],
        request: ModelTrainingRequest,
    ) -> tuple[ModelEvaluationRecord, ...]:
        """구간마다 그 구간의 학습 표본만으로 학습해 검증한다(표본 밖 평가)."""
        records: list[ModelEvaluationRecord] = []
        for fold in folds:
            training = tuple(sample for sample in samples if sample.signal_date <= fold.train_end)
            validation = tuple(
                sample
                for sample in samples
                if fold.valid_start <= sample.signal_date <= fold.valid_end
            )
            if len(training) < request.min_train_samples or not validation:
                continue
            fitted = _fit(training, request)
            outcomes = _daily_outcomes(fitted, validation)
            metrics = fold_metrics(outcomes, top_k=request.top_k)
            sample_count = int(metrics["sample_count"])
            records.extend(
                ModelEvaluationRecord(
                    fold_index=fold.index,
                    valid_start=fold.valid_start,
                    valid_end=fold.valid_end,
                    sample_count=sample_count,
                    metric_name=name,
                    metric_value=metrics[name],
                )
                for name in ("rank_ic", "top_k_excess", "hit_rate")
            )
        return tuple(records)


def _fit(
    training: tuple[TrainingSample, ...],
    request: ModelTrainingRequest,
) -> PredictiveModel:
    """요청한 알고리즘으로 학습한다. 알 수 없는 이름은 추측하지 않고 거부한다."""
    if request.algorithm == RIDGE_ALGORITHM:
        return train_ridge(
            training,
            FEATURE_NAMES,
            alpha=request.alpha,
            seed=request.seed,
            min_samples=request.min_train_samples,
        )
    if request.algorithm == LIGHTGBM_ALGORITHM:
        return train_lightgbm(
            training,
            FEATURE_NAMES,
            LightGbmSettings(
                parameters=default_parameters(seed=request.seed),
                seed=request.seed,
                min_samples=request.min_train_samples,
            ),
        )
    message = f"unknown training algorithm: {request.algorithm!r}"
    raise ValueError(message)


def _daily_outcomes(
    model: PredictiveModel,
    validation: tuple[TrainingSample, ...],
) -> tuple[tuple[date, dict[str, float], dict[str, Decimal]], ...]:
    grouped: dict[date, tuple[dict[str, float], dict[str, Decimal]]] = {}
    for sample in validation:
        predictions, actual = grouped.setdefault(sample.signal_date, ({}, {}))
        predictions[sample.symbol] = model.predict(sample.features)
        # 계약의 상위 K 초과수익·적중률은 순위가 아니라 원 초과수익 기준이다. 순위를 넣으면
        # 값이 항상 양수라 적중률이 늘 100%로 나온다(2026-08-22 실측 결함).
        actual[sample.symbol] = Decimal(repr(sample.excess))
    return tuple(
        (signal_date, grouped[signal_date][0], grouped[signal_date][1])
        for signal_date in sorted(grouped)
    )


def _importances(
    model_id: UUID,
    model: PredictiveModel,
) -> tuple[FeatureImportanceRecord, ...]:
    """중요도 정의는 모델이 갖는다(선형은 계수 절대값, 트리는 분할 이득)."""
    return tuple(
        FeatureImportanceRecord(model_id=model_id, feature_name=name, importance=value)
        for name, value in sorted(model.importances().items())
    )


def _hyperparameters_json(request: ModelTrainingRequest) -> str:
    return json.dumps(
        {
            "algorithm": request.algorithm,
            "alpha": request.alpha,
            "min_train_days": request.min_train_days,
            "min_train_samples": request.min_train_samples,
            "top_k": request.top_k,
            "valid_days": request.valid_days,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _out_of_sample_start(
    trading_dates: tuple[date, ...],
    train_end: date,
    embargo_days: int,
) -> date | None:
    """학습 종료 뒤 엠바고가 끝나는 첫 거래일.

    학습 시점에는 전체 달력이 있으므로 거래일 단위로 정확히 셀 수 있다. 백테스트 창의 달력만으로는
    학습 창과의 간격을 셀 수 없어 이 값을 저장해 둔다(ADR-0012 결정 4).
    """
    try:
        position = trading_dates.index(train_end)
    except ValueError:
        return None
    target = position + embargo_days + 1
    if target >= len(trading_dates):
        return None
    return trading_dates[target]
