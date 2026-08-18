import argparse
from datetime import UTC, date, datetime
from decimal import Decimal

import anyio

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
from auto_stock_trading.adapters.database.strategy_backtest_store import (
    PostgresBacktestStore,
)
from auto_stock_trading.application.backtests.runner import BacktestRequest, BacktestRunner
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
from auto_stock_trading.domain.strategies.ma_rsi import MaRsiParameters
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
    arguments = parser.parse_args(namespace=Arguments())
    print(anyio.run(run_ma_rsi_backtest, arguments))  # noqa: T201


if __name__ == "__main__":
    main()
