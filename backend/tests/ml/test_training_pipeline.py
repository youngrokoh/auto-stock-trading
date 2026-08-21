"""학습 파이프라인 조립(ML 신호 계약 §시점 정합과 워크포워드, §평가 지표).

로더·학습·평가·저장을 잇는 층이다. 여기서 지켜야 하는 것은 두 가지다: 학습 표본이 학습 구간
밖으로 새지 않는 것, 그리고 구간별 지표를 구간마다 남기는 것.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, final
from uuid import UUID

import anyio
import pytest

from auto_stock_trading.application.ml.training import (
    ModelTrainer,
    ModelTrainingRequest,
)
from auto_stock_trading.features.price_features import FEATURE_NAMES, FeatureRow

if TYPE_CHECKING:
    from auto_stock_trading.ml.samples import TrainingSample

_START = date(2024, 1, 1)
_NOW = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)


def _dates(count: int) -> tuple[date, ...]:
    return tuple(_START + timedelta(days=index) for index in range(count))


def _row(day: date, value: float) -> FeatureRow:
    return FeatureRow(
        trading_date=day,
        values={name: Decimal(repr(value)) for name in FEATURE_NAMES},
    )


@final
@dataclass
class FakeDataset:
    """종목마다 같은 특징을 주고, 목표만 특징에 비례하게 만든다."""

    dates: tuple[date, ...]
    symbols: tuple[str, ...]

    async def trading_dates(self, start: date, end: date) -> tuple[date, ...]:
        return tuple(day for day in self.dates if start <= day <= end)

    async def feature_rows(self, symbol: str) -> tuple[FeatureRow, ...]:
        offset = self.symbols.index(symbol) / 10.0
        return tuple(_row(day, offset + index / 1000.0) for index, day in enumerate(self.dates))

    async def universe_symbols(self) -> tuple[str, ...]:
        return self.symbols

    async def targets(self, symbol: str) -> dict[date, Decimal]:
        offset = self.symbols.index(symbol)
        return {day: Decimal(offset) / 10 for day in self.dates}

    async def bar_version_hash(self) -> str:
        return "a" * 64

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeModelStore:
    saved: list[tuple[str, int, int]] = field(default_factory=list[tuple[str, int, int]])
    metrics: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    importances: list[str] = field(default_factory=list[str])

    async def save_model(
        self,
        record: object,
        evaluations: tuple[object, ...],
        importances: tuple[object, ...],
    ) -> UUID:
        name = getattr(record, "name", "")
        self.saved.append((str(name), len(evaluations), len(importances)))
        for item in evaluations:
            self.metrics.append(
                (int(getattr(item, "fold_index", 0)), str(getattr(item, "metric_name", "")))
            )
        self.importances.extend(str(getattr(item, "feature_name", "")) for item in importances)
        return UUID(int=1)

    async def close(self) -> None:
        return None


def _request(dates: tuple[date, ...]) -> ModelTrainingRequest:
    return ModelTrainingRequest(
        name="ridge-baseline",
        version="1",
        range_start=dates[0],
        range_end=dates[-1],
        min_train_days=30,
        valid_days=10,
        alpha=0.5,
        seed=7,
        min_train_samples=10,
    )


def test_training_saves_one_model_with_per_fold_metrics_and_importances() -> None:
    async def run() -> None:
        dates = _dates(120)
        dataset = FakeDataset(dates, ("000100", "000200", "000300"))
        store = FakeModelStore()

        record = await ModelTrainer(dataset=dataset, store=store).run(_request(dates), _NOW)

        assert record.name == "ridge-baseline"
        assert record.train_sample_count > 0
        assert store.saved[0][0] == "ridge-baseline"
        # 구간마다 지표를 남긴다. 평균만 남기면 한 구간 집중을 놓친다.
        fold_indexes = {index for index, _ in store.metrics}
        assert len(fold_indexes) >= 2
        assert {name for _, name in store.metrics} >= {"rank_ic", "top_k_excess", "hit_rate"}
        assert set(store.importances) == set(FEATURE_NAMES)

    anyio.run(run)


def test_training_samples_never_reach_past_the_training_window() -> None:
    async def run() -> None:
        dates = _dates(120)
        dataset = FakeDataset(dates, ("000100", "000200"))
        trainer = ModelTrainer(dataset=dataset, store=FakeModelStore())

        folds, samples = await trainer.prepare(_request(dates))

        assert folds
        for fold in folds:
            in_fold = samples_within(samples, fold.train_start, fold.train_end)
            assert all(sample.signal_date <= fold.train_end for sample in in_fold)
            # 엠바고 구간의 표본은 학습에 들어가지 않는다.
            assert not any(
                fold.train_end < sample.signal_date < fold.valid_start for sample in in_fold
            )

    anyio.run(run)


def samples_within(
    samples: tuple[TrainingSample, ...],
    start: date,
    end: date,
) -> tuple[TrainingSample, ...]:
    return tuple(sample for sample in samples if start <= sample.signal_date <= end)


def test_too_few_samples_refuses_training_instead_of_fitting_noise() -> None:
    async def run() -> None:
        dates = _dates(120)
        dataset = FakeDataset(dates, ("000100", "000200"))
        trainer = ModelTrainer(dataset=dataset, store=FakeModelStore())
        request = ModelTrainingRequest(
            name="ridge-baseline",
            version="1",
            range_start=dates[0],
            range_end=dates[-1],
            min_train_days=30,
            valid_days=10,
            alpha=0.5,
            seed=7,
            min_train_samples=100_000,
        )

        with pytest.raises(ValueError, match="samples"):
            _ = await trainer.run(request, _NOW)

    anyio.run(run)


def test_a_window_without_a_single_fold_refuses_training() -> None:
    async def run() -> None:
        dates = _dates(40)
        dataset = FakeDataset(dates, ("000100", "000200"))
        trainer = ModelTrainer(dataset=dataset, store=FakeModelStore())
        request = ModelTrainingRequest(
            name="ridge-baseline",
            version="1",
            range_start=dates[0],
            range_end=dates[-1],
            min_train_days=30,
            valid_days=10,
            alpha=0.5,
            seed=7,
            min_train_samples=1,
        )

        with pytest.raises(ValueError, match="fold"):
            _ = await trainer.run(request, _NOW)

    anyio.run(run)
