from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.market_data_statements import instrument_id_for
from auto_stock_trading.adapters.database.strategy_backtest_rows import (
    BacktestRunInstrumentRow,
    BacktestRunRow,
    BacktestTradeRow,
)
from auto_stock_trading.adapters.database.strategy_backtest_store import PostgresBacktestStore
from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.strategies.backtest_metrics import BacktestMetrics, EquityPoint
from auto_stock_trading.domain.strategies.portfolio_backtest import (
    PortfolioSkipReason,
    PortfolioTrade,
)
from auto_stock_trading.domain.strategies.records import PortfolioRunRecord
from auto_stock_trading.settings.runtime import Settings

_NOW: Final = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
# CI는 빈 DB로 돌므로 테스트가 스스로 종목을 만든다(실데이터 가정 금지).
_UNIVERSE: Final = ("900110", "900120")


def _metrics() -> BacktestMetrics:
    return BacktestMetrics(
        total_return_pct=Decimal("12.34"),
        pre_cost_return_pct=Decimal("13.00"),
        benchmark_return_pct=Decimal("10.00"),
        excess_return_pct=Decimal("2.34"),
        mdd_pct=Decimal("-5.00"),
        sharpe=Decimal("0.9000"),
        turnover_pct=Decimal("120.00"),
        total_fee=Decimal(1000),
        total_slippage=Decimal(5000),
        total_tax=Decimal(2000),
        trade_count=2,
    )


def _record(run_id: UUID) -> PortfolioRunRecord:
    return PortfolioRunRecord(
        run_id=run_id,
        strategy_name="cross-momentum",
        strategy_version="1",
        parameters_json='{"holdings":2,"lookback_days":126}',
        universe=_UNIVERSE,
        benchmark_symbol="069500",
        range_start=date(2025, 1, 2),
        range_end=date(2026, 8, 20),
        initial_cash=Decimal(10_000_000),
        signal_method="cross_sectional_momentum",
        engine_version="portfolio-1",
        cost_rule_versions="research-krx-2025,research-krx-2026",
        input_bar_version_hash="a" * 64,
        action_version_hash="b" * 64,
        benchmark_dataset_id=None,
        status="completed",
        failure_code=None,
        metrics=_metrics(),
        created_at=_NOW,
    )


def _trades() -> tuple[PortfolioTrade, ...]:
    return (
        PortfolioTrade(
            sequence=1,
            symbol=_UNIVERSE[0],
            signal_date=date(2025, 1, 31),
            execution_date=date(2025, 2, 3),
            action="buy",
            quantity=10,
            price=Decimal(70000),
            gross_amount=Decimal(700000),
            fee=Decimal(140),
            slippage=Decimal(700),
            tax=Decimal(0),
            skip_reason=None,
        ),
        PortfolioTrade(
            sequence=2,
            symbol=_UNIVERSE[1],
            signal_date=date(2025, 1, 31),
            execution_date=None,
            action="buy",
            quantity=0,
            price=None,
            gross_amount=Decimal(0),
            fee=Decimal(0),
            slippage=Decimal(0),
            tax=Decimal(0),
            skip_reason=PortfolioSkipReason.MISSING_CONFIRMED_BAR,
        ),
    )


def test_a_portfolio_run_stores_its_universe_as_rows_without_a_lead_instrument() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        run_id = uuid4()
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresBacktestStore.from_connection(connection)
            try:
                _ = await connection.execute(
                    delete(BacktestRunRow).where(BacktestRunRow.id == run_id)
                )
                _ = await connection.execute(
                    delete(InstrumentRow).where(InstrumentRow.symbol.in_(_UNIVERSE))
                )
                for symbol in _UNIVERSE:
                    _ = await connection.execute(
                        insert(InstrumentRow).values(
                            id=instrument_id_for(
                                country="KR",
                                exchange="XKRX",
                                symbol=symbol,
                                product_type=ProductType.STOCK,
                                currency="KRW",
                            ),
                            country="KR",
                            exchange="XKRX",
                            symbol=symbol,
                            product_type=ProductType.STOCK.value,
                            currency="KRW",
                            name=f"테스트{symbol}",
                            trading_status="active",
                            source="TEST",
                            source_as_of=_NOW.date(),
                            created_at=_NOW,
                            updated_at=_NOW,
                        )
                    )
                await store.save_portfolio_run(
                    _record(run_id),
                    _trades(),
                    (
                        EquityPoint(
                            trading_date=date(2025, 1, 2),
                            cash=Decimal(10_000_000),
                            position_value=Decimal(0),
                            nav=Decimal(10_000_000),
                        ),
                    ),
                )

                stored = (
                    await connection.execute(
                        select(
                            BacktestRunRow.instrument_id,
                            BacktestRunRow.signal_method,
                            BacktestRunRow.total_return_pct,
                        ).where(BacktestRunRow.id == run_id)
                    )
                ).all()
                assert stored == [(None, "cross_sectional_momentum", Decimal("12.34"))]

                universe = (
                    await connection.execute(
                        select(BacktestRunInstrumentRow.symbol)
                        .where(BacktestRunInstrumentRow.run_id == run_id)
                        .order_by(BacktestRunInstrumentRow.symbol)
                    )
                ).scalars()
                assert tuple(universe.all()) == _UNIVERSE

                trades = (
                    await connection.execute(
                        select(
                            BacktestTradeRow.symbol,
                            BacktestTradeRow.reason,
                            BacktestTradeRow.skip_reason,
                        )
                        .where(BacktestTradeRow.run_id == run_id)
                        .order_by(BacktestTradeRow.sequence)
                    )
                ).all()
                assert trades == [
                    (_UNIVERSE[0], "rebalance", None),
                    (_UNIVERSE[1], "rebalance", "missing_confirmed_bar"),
                ]
            finally:
                await store.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)
