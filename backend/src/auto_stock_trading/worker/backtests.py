import argparse
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from auto_stock_trading.ml.models import PredictiveModel
    from auto_stock_trading.ml.records import ModelRecord

from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_adjustment_reader import (
    PostgresAdjustedPriceReader,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_reader import (
    PostgresCorporateActionReader,
)
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_stock_store import PostgresStockStore
from auto_stock_trading.adapters.database.ml_dataset_reader import (
    DatasetRequest,
    MarketDataTrainingDataset,
)
from auto_stock_trading.adapters.database.ml_model_reader import PostgresModelReader
from auto_stock_trading.adapters.database.strategy_backtest_store import (
    PostgresBacktestStore,
)
from auto_stock_trading.adapters.database.strategy_fundamentals_reader import (
    PostgresStrategyFundamentalsReader,
)
from auto_stock_trading.application.backtests.ml_signals import ModelWindow, ml_rank_strategy
from auto_stock_trading.application.backtests.portfolio_runner import (
    PortfolioRequest,
    PortfolioRunner,
)
from auto_stock_trading.application.backtests.portfolio_strategies import (
    composite_strategy,
    momentum_strategy,
)
from auto_stock_trading.application.backtests.runner import BacktestRequest, BacktestRunner
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
from auto_stock_trading.domain.strategies.composite_rank import CompositeParameters
from auto_stock_trading.domain.strategies.ma_rsi import MaRsiParameters
from auto_stock_trading.domain.strategies.momentum import MomentumParameters
from auto_stock_trading.features.feature_set import feature_names, uses_fundamentals
from auto_stock_trading.ml.lightgbm_model import LIGHTGBM_ALGORITHM, LightGbmModel
from auto_stock_trading.ml.ridge import RIDGE_ALGORITHM, RidgeCoefficients
from auto_stock_trading.settings.runtime import Settings


class Arguments(argparse.Namespace):
    symbol: str = "005930"
    benchmark: str = "069500"
    start_date: str = "2025-01-02"
    end_date: str = "2026-08-14"
    initial_cash: str = "10000000"
    signal_method: str = AdjustmentMethod.TOTAL_RETURN.value
    short_period: int = 5
    long_period: int = 20
    rsi_period: int = 14
    rsi_overbought: str = "70"
    cross_momentum: bool = False
    composite_rank: bool = False
    ml_rank: bool = False
    model_name: str = "ridge-baseline"
    model_version: str = "1"
    lookback_days: int = 126
    holdings: int = 10


async def run_cross_momentum_backtest(arguments: Arguments) -> str:
    """저장된 유니버스 전 종목으로 횡단면 모멘텀 실행을 만든다(계약 v2)."""
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    market_data = PostgresMarketDataRepository.from_url(database_url)
    adjusted = PostgresAdjustedPriceReader.from_url(database_url)
    corporate_actions = PostgresCorporateActionReader.from_url(database_url)
    universe_store = PostgresStockStore.from_url(database_url)
    store = PostgresBacktestStore.from_url(database_url)
    runner = PortfolioRunner(
        calendar=calendar,
        market_data=market_data,
        adjusted_prices=adjusted,
        corporate_actions=corporate_actions,
        store=store,
    )
    try:
        universe = await universe_store.universe_symbols()
        request = PortfolioRequest(
            universe=universe,
            benchmark_symbol=arguments.benchmark,
            range_start=date.fromisoformat(arguments.start_date),
            range_end=date.fromisoformat(arguments.end_date),
            initial_cash=Decimal(arguments.initial_cash),
            benchmark_method=AdjustmentMethod(arguments.signal_method),
            strategy=momentum_strategy(
                MomentumParameters(
                    lookback_days=arguments.lookback_days,
                    holdings=arguments.holdings,
                )
            ),
        )
        record = await runner.run(request, datetime.now(UTC))
    finally:
        await universe_store.close()
        await store.close()
        await corporate_actions.close()
        await adjusted.close()
        await market_data.close()
        await calendar.close()
    metrics = record.metrics
    if metrics is None:
        return f"failed run_id={record.run_id} failure_code={record.failure_code}"
    return (
        f"completed run_id={record.run_id} universe={len(record.universe)} "
        f"total_return={metrics.total_return_pct} benchmark={metrics.benchmark_return_pct} "
        f"mdd={metrics.mdd_pct} trades={metrics.trade_count} turnover={metrics.turnover_pct}"
    )


def _restore_model(record: ModelRecord) -> PredictiveModel:
    """저장된 산출물을 알고리즘에 맞게 복원한다. 모르는 알고리즘은 추측하지 않는다."""
    if record.algorithm == RIDGE_ALGORITHM:
        return RidgeCoefficients.from_json(record.artifact)
    if record.algorithm == LIGHTGBM_ALGORITHM:
        return LightGbmModel.from_artifact(record.artifact, feature_names(record.feature_version))
    message = f"unknown model algorithm: {record.algorithm!r}"
    raise ValueError(message)


async def run_ml_rank_backtest(arguments: Arguments) -> str:
    """저장된 모델로 추론만 하는 ML 순위 실행(ADR-0012). 학습은 하지 않는다."""
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    market_data = PostgresMarketDataRepository.from_url(database_url)
    adjusted = PostgresAdjustedPriceReader.from_url(database_url)
    corporate_actions = PostgresCorporateActionReader.from_url(database_url)
    universe_store = PostgresStockStore.from_url(database_url)
    models = PostgresModelReader.from_url(database_url)
    features_market_data = PostgresMarketDataRepository.from_url(database_url)
    store = PostgresBacktestStore.from_url(database_url)
    fundamentals: PostgresStrategyFundamentalsReader | None = None
    runner = PortfolioRunner(
        calendar=calendar,
        market_data=market_data,
        adjusted_prices=adjusted,
        corporate_actions=corporate_actions,
        store=store,
    )
    try:
        record = await models.read_model(arguments.model_name, arguments.model_version)
        if record is None:
            return f"failed reason=model_not_found name={arguments.model_name}"
        model = _restore_model(record)
        universe = await universe_store.universe_symbols()
        range_start = date.fromisoformat(arguments.start_date)
        range_end = date.fromisoformat(arguments.end_date)
        # 특징은 모델 학습과 같은 계산기로 만든다. 창은 시그널일 계산에 필요한 만큼 앞으로 넓힌다.
        if uses_fundamentals(record.feature_version):
            fundamentals = PostgresStrategyFundamentalsReader.from_url(database_url)
        dataset = MarketDataTrainingDataset(
            features_market_data,
            DatasetRequest(
                universe=universe,
                benchmark_symbol=arguments.benchmark,
                range_start=record.train_start,
                range_end=range_end,
                feature_version=record.feature_version,
            ),
            fundamentals,
        )
        names = feature_names(record.feature_version)
        features: dict[str, dict[date, dict[str, float]]] = {}
        for symbol in universe:
            rows = await dataset.feature_rows(symbol)
            if rows:
                features[symbol] = {
                    row.trading_date: {name: float(row.values[name]) for name in names}
                    for row in rows
                }
        request = PortfolioRequest(
            universe=universe,
            benchmark_symbol=arguments.benchmark,
            range_start=range_start,
            range_end=range_end,
            initial_cash=Decimal(arguments.initial_cash),
            benchmark_method=AdjustmentMethod(arguments.signal_method),
            strategy=ml_rank_strategy(
                CompositeParameters(
                    lookback_days=arguments.lookback_days,
                    holdings=arguments.holdings,
                ),
                model=model,
                window=ModelWindow(
                    train_start=record.train_start,
                    train_end=record.train_end,
                    embargo_days=record.embargo_days,
                    out_of_sample_start=record.out_of_sample_start,
                ),
                features=features,
                feature_version=record.feature_version,
            ),
        )
        run_record = await runner.run(request, datetime.now(UTC))
    finally:
        if fundamentals is not None:
            await fundamentals.close()
        await store.close()
        await features_market_data.close()
        await models.close()
        await universe_store.close()
        await corporate_actions.close()
        await adjusted.close()
        await market_data.close()
        await calendar.close()
    metrics = run_record.metrics
    if metrics is None:
        return f"failed run_id={run_record.run_id} failure_code={run_record.failure_code}"
    return (
        f"completed run_id={run_record.run_id} model={arguments.model_name} "
        f"total_return={metrics.total_return_pct} benchmark={metrics.benchmark_return_pct} "
        f"mdd={metrics.mdd_pct} trades={metrics.trade_count} turnover={metrics.turnover_pct}"
    )


async def run_composite_rank_backtest(arguments: Arguments) -> str:
    """저장된 유니버스 전 종목으로 가치·수익성·모멘텀 종합 순위 실행을 만든다(계약 v3)."""
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    market_data = PostgresMarketDataRepository.from_url(database_url)
    adjusted = PostgresAdjustedPriceReader.from_url(database_url)
    corporate_actions = PostgresCorporateActionReader.from_url(database_url)
    universe_store = PostgresStockStore.from_url(database_url)
    fundamentals = PostgresStrategyFundamentalsReader.from_url(database_url)
    store = PostgresBacktestStore.from_url(database_url)
    runner = PortfolioRunner(
        calendar=calendar,
        market_data=market_data,
        adjusted_prices=adjusted,
        corporate_actions=corporate_actions,
        store=store,
    )
    try:
        universe = await universe_store.universe_symbols()
        facts = await fundamentals.read_annual_facts(universe)
        request = PortfolioRequest(
            universe=universe,
            benchmark_symbol=arguments.benchmark,
            range_start=date.fromisoformat(arguments.start_date),
            range_end=date.fromisoformat(arguments.end_date),
            initial_cash=Decimal(arguments.initial_cash),
            benchmark_method=AdjustmentMethod(arguments.signal_method),
            strategy=composite_strategy(
                CompositeParameters(
                    lookback_days=arguments.lookback_days,
                    holdings=arguments.holdings,
                ),
                facts,
            ),
        )
        record = await runner.run(request, datetime.now(UTC))
    finally:
        await store.close()
        await fundamentals.close()
        await universe_store.close()
        await corporate_actions.close()
        await adjusted.close()
        await market_data.close()
        await calendar.close()
    metrics = record.metrics
    if metrics is None:
        return f"failed run_id={record.run_id} failure_code={record.failure_code}"
    return (
        f"completed run_id={record.run_id} universe={len(record.universe)} "
        f"report_hash={record.input_report_version_hash} "
        f"total_return={metrics.total_return_pct} benchmark={metrics.benchmark_return_pct} "
        f"mdd={metrics.mdd_pct} trades={metrics.trade_count} turnover={metrics.turnover_pct}"
    )


async def run_ma_rsi_backtest(arguments: Arguments) -> str:
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    market_data = PostgresMarketDataRepository.from_url(database_url)
    adjusted = PostgresAdjustedPriceReader.from_url(database_url)
    corporate_actions = PostgresCorporateActionReader.from_url(database_url)
    store = PostgresBacktestStore.from_url(database_url)
    runner = BacktestRunner(
        calendar=calendar,
        market_data=market_data,
        adjusted_prices=adjusted,
        corporate_actions=corporate_actions,
        store=store,
    )
    request = BacktestRequest(
        symbol=arguments.symbol,
        benchmark_symbol=arguments.benchmark,
        range_start=date.fromisoformat(arguments.start_date),
        range_end=date.fromisoformat(arguments.end_date),
        initial_cash=Decimal(arguments.initial_cash),
        signal_method=AdjustmentMethod(arguments.signal_method),
        parameters=MaRsiParameters(
            short_period=arguments.short_period,
            long_period=arguments.long_period,
            rsi_period=arguments.rsi_period,
            rsi_overbought=Decimal(arguments.rsi_overbought),
        ),
    )
    try:
        record = await runner.run(request, datetime.now(UTC))
    finally:
        await calendar.close()
        await market_data.close()
        await adjusted.close()
        await corporate_actions.close()
        await store.close()
    if record.status != "completed":
        return f"failed run_id={record.run_id} failure_code={record.failure_code}"
    metrics = record.metrics
    if metrics is None:
        return f"completed run_id={record.run_id} (no metrics)"
    return (
        f"completed run_id={record.run_id} "
        f"total_return={metrics.total_return_pct}% "
        f"benchmark={metrics.benchmark_return_pct}% "
        f"excess={metrics.excess_return_pct}% "
        f"mdd={metrics.mdd_pct}% sharpe={metrics.sharpe} "
        f"turnover={metrics.turnover_pct}% trades={metrics.trade_count} "
        f"costs(fee={metrics.total_fee}, slippage={metrics.total_slippage}, "
        f"tax={metrics.total_tax})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="규칙형 전략 백테스트 실행")
    _ = parser.add_argument("--symbol", default=Arguments.symbol)
    _ = parser.add_argument("--benchmark", default=Arguments.benchmark)
    _ = parser.add_argument("--start-date", default=Arguments.start_date)
    _ = parser.add_argument("--end-date", default=Arguments.end_date)
    _ = parser.add_argument("--initial-cash", default=Arguments.initial_cash)
    _ = parser.add_argument("--signal-method", default=Arguments.signal_method)
    _ = parser.add_argument("--short-period", type=int, default=Arguments.short_period)
    _ = parser.add_argument("--long-period", type=int, default=Arguments.long_period)
    _ = parser.add_argument("--rsi-period", type=int, default=Arguments.rsi_period)
    _ = parser.add_argument("--rsi-overbought", default=Arguments.rsi_overbought)
    _ = parser.add_argument("--cross-momentum", action="store_true")
    _ = parser.add_argument("--composite-rank", action="store_true")
    _ = parser.add_argument("--ml-rank", action="store_true")
    _ = parser.add_argument("--model-name", default="ridge-baseline")
    _ = parser.add_argument("--model-version", default="1")
    _ = parser.add_argument("--lookback-days", type=int, default=Arguments.lookback_days)
    _ = parser.add_argument("--holdings", type=int, default=Arguments.holdings)
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.ml_rank:
        print(anyio.run(run_ml_rank_backtest, arguments))  # noqa: T201
    elif arguments.composite_rank:
        print(anyio.run(run_composite_rank_backtest, arguments))  # noqa: T201
    elif arguments.cross_momentum:
        print(anyio.run(run_cross_momentum_backtest, arguments))  # noqa: T201
    else:
        print(anyio.run(run_ma_rsi_backtest, arguments))  # noqa: T201


if __name__ == "__main__":
    main()
