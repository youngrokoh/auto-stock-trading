"""다종목 실행이 읽기 API에서 탈락하지 않는지 확인한다.

실측 결함(2026-08-21): 읽기 어댑터가 `instrument_id`로 종목 테이블을 inner join해,
대표 종목이 없는 다종목 실행이 목록·상세에서 통째로 사라졌다. 저장·검증된 실행을 읽기
경로가 없는 것처럼 취급하면 계약의 필수 조회 취지에 어긋난다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.market_data_statements import instrument_id_for
from auto_stock_trading.adapters.database.strategy_backtest_reader import PostgresBacktestReader
from auto_stock_trading.adapters.database.strategy_backtest_rows import BacktestRunRow
from auto_stock_trading.adapters.database.strategy_backtest_store import PostgresBacktestStore
from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.strategies.backtest_metrics import BacktestMetrics, EquityPoint
from auto_stock_trading.domain.strategies.portfolio_backtest import PortfolioTrade
from auto_stock_trading.domain.strategies.records import PortfolioRunRecord
from auto_stock_trading.settings.runtime import Settings

_NOW: Final = datetime(2026, 8, 21, 6, 0, tzinfo=UTC)
_UNIVERSE: Final = ("900310", "900320", "900330")
_TRADED: Final = ("900310", "900320")


def _metrics() -> BacktestMetrics:
    return BacktestMetrics(
        total_return_pct=Decimal("55.56"),
        pre_cost_return_pct=Decimal("57.44"),
        benchmark_return_pct=Decimal("254.49"),
        excess_return_pct=Decimal("-198.93"),
        mdd_pct=Decimal("-57.13"),
        sharpe=Decimal("0.7852"),
        turnover_pct=Decimal("492.45"),
        total_fee=Decimal(1000),
        total_slippage=Decimal(2000),
        total_tax=Decimal(3000),
        trade_count=2,
    )


def _record(run_id: UUID) -> PortfolioRunRecord:
    return PortfolioRunRecord(
        run_id=run_id,
        strategy_name="cross-momentum",
        strategy_version="1",
        parameters_json='{"holdings":10,"lookback_days":126}',
        universe=_UNIVERSE,
        benchmark_symbol="069500",
        range_start=date(2025, 1, 2),
        range_end=date(2026, 8, 14),
        initial_cash=Decimal(10_000_000),
        signal_method="cross_sectional_momentum",
        engine_version="portfolio-1",
        cost_rule_versions='["research-krx-2025"]',
        input_bar_version_hash="a" * 64,
        action_version_hash="b" * 64,
        input_report_version_hash=None,
        benchmark_dataset_id=None,
        status="completed",
        failure_code=None,
        metrics=_metrics(),
        created_at=_NOW,
    )


def _trades() -> tuple[PortfolioTrade, ...]:
    return tuple(
        PortfolioTrade(
            sequence=index + 1,
            symbol=symbol,
            signal_date=date(2025, 7, 31),
            execution_date=date(2025, 8, 1),
            action="buy",
            quantity=1,
            price=Decimal(1000),
            gross_amount=Decimal(1000),
            fee=Decimal(1),
            slippage=Decimal(1),
            tax=Decimal(0),
            skip_reason=None,
        )
        for index, symbol in enumerate(_TRADED)
    )


def test_a_portfolio_run_is_listed_and_readable_with_its_universe() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        run_id = uuid4()
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresBacktestStore.from_connection(connection)
            reader = PostgresBacktestReader.from_connection(connection)
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

                listed = await reader.runs(20)
                found = [item for item in listed if item.run_id == run_id]
                assert len(found) == 1
                assert found[0].symbol is None
                assert found[0].universe == _UNIVERSE
                assert found[0].traded_symbols == _TRADED

                detail = await reader.run(run_id)
                assert detail is not None
                assert detail.universe == _UNIVERSE
                assert detail.traded_symbols == _TRADED

                # 저장된 사유는 전략마다 다르다. 읽기 경로가 한 전략의 enum으로 되검증하면
                # 다종목 실행의 체결 목록이 500으로 깨진다(2026-08-21 실측).
                trades = await reader.trades(run_id)
                assert [(item.symbol, item.action, item.reason) for item in trades] == [
                    (_TRADED[0], "buy", "rebalance"),
                    (_TRADED[1], "buy", "rebalance"),
                ]
            finally:
                await reader.close()
                await store.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)
