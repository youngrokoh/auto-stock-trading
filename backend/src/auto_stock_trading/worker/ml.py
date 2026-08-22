"""ML 학습 수동 진입점(ML 신호 계약 §구현 순서).

예약하지 않는다. 학습은 사람이 시작하고, 결과는 `ml` 스키마에 남는다.
"""

import argparse
from datetime import UTC, date, datetime

import anyio

from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_stock_store import PostgresStockStore
from auto_stock_trading.adapters.database.ml_dataset_reader import MarketDataTrainingDataset
from auto_stock_trading.adapters.database.ml_model_store import PostgresModelStore
from auto_stock_trading.application.ml.training import ModelTrainer, ModelTrainingRequest
from auto_stock_trading.features.splits import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_MIN_TRAIN_DAYS,
    DEFAULT_VALID_DAYS,
)
from auto_stock_trading.ml.lightgbm_model import LIGHTGBM_ALGORITHM
from auto_stock_trading.ml.ridge import RIDGE_ALGORITHM
from auto_stock_trading.settings.runtime import Settings


class Arguments(argparse.Namespace):
    train_ridge: bool = False
    algorithm: str = RIDGE_ALGORITHM
    name: str = "ridge-baseline"
    model_version: str = "1"
    benchmark: str = "069500"
    start_date: str = "2020-01-02"
    end_date: str = "2026-08-20"
    min_train_days: int = DEFAULT_MIN_TRAIN_DAYS
    valid_days: int = DEFAULT_VALID_DAYS
    embargo_days: int = DEFAULT_EMBARGO_DAYS
    alpha: float = 1.0
    seed: int = 7
    min_train_samples: int = 1000


async def train_ridge_baseline(arguments: Arguments) -> str:
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    market_data = PostgresMarketDataRepository.from_url(database_url)
    universe_store = PostgresStockStore.from_url(database_url)
    store = PostgresModelStore.from_url(database_url)
    try:
        universe = await universe_store.universe_symbols()
        dataset = MarketDataTrainingDataset(
            market_data,
            universe,
            arguments.benchmark,
            date.fromisoformat(arguments.start_date),
            date.fromisoformat(arguments.end_date),
        )
        record = await ModelTrainer(dataset=dataset, store=store).run(
            ModelTrainingRequest(
                name=arguments.name,
                version=arguments.model_version,
                algorithm=arguments.algorithm,
                range_start=date.fromisoformat(arguments.start_date),
                range_end=date.fromisoformat(arguments.end_date),
                min_train_days=arguments.min_train_days,
                valid_days=arguments.valid_days,
                embargo_days=arguments.embargo_days,
                alpha=arguments.alpha,
                seed=arguments.seed,
                min_train_samples=arguments.min_train_samples,
            ),
            datetime.now(UTC),
        )
    finally:
        await store.close()
        await universe_store.close()
        await market_data.close()
    return (
        f"trained model_id={record.model_id} name={record.name} version={record.version} "
        f"algorithm={record.algorithm} "
        f"train={record.train_start}~{record.train_end} samples={record.train_sample_count} "
        f"universe={record.universe_size} features={record.feature_version}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--train-ridge", action="store_true")
    _ = parser.add_argument(
        "--algorithm",
        default=RIDGE_ALGORITHM,
        choices=(RIDGE_ALGORITHM, LIGHTGBM_ALGORITHM),
    )
    _ = parser.add_argument("--name", default="ridge-baseline")
    _ = parser.add_argument("--model-version", default="1")
    _ = parser.add_argument("--benchmark", default="069500")
    _ = parser.add_argument("--start-date", default="2020-01-02")
    _ = parser.add_argument("--end-date", default="2026-08-20")
    _ = parser.add_argument("--min-train-days", type=int, default=DEFAULT_MIN_TRAIN_DAYS)
    _ = parser.add_argument("--valid-days", type=int, default=DEFAULT_VALID_DAYS)
    _ = parser.add_argument("--embargo-days", type=int, default=DEFAULT_EMBARGO_DAYS)
    _ = parser.add_argument("--alpha", type=float, default=1.0)
    _ = parser.add_argument("--seed", type=int, default=7)
    _ = parser.add_argument("--min-train-samples", type=int, default=1000)
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.train_ridge:
        print(anyio.run(train_ridge_baseline, arguments))  # noqa: T201
    else:
        parser.error("choose --train-ridge")


if __name__ == "__main__":
    main()
