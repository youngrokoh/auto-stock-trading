from datetime import UTC, date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.domain.strategies.backtest import (
    TradeSkipReason,
)
from auto_stock_trading.domain.strategies.backtest_metrics import (
    BacktestMetrics,
    EquityPoint,
)
from auto_stock_trading.domain.strategies.ma_rsi import SignalAction, SignalReason
from auto_stock_trading.domain.strategies.records import BacktestRunRecord, BacktestTradeRecord
from auto_stock_trading.settings.runtime import Environment, Settings

_NOW = datetime(2026, 8, 18, 2, 0, tzinfo=UTC)
_RUN_ID = UUID("00000000-0000-0000-0000-000000000101")
_FAILED_RUN_ID = UUID("00000000-0000-0000-0000-000000000102")
_MISSING_RUN_ID = UUID("00000000-0000-0000-0000-000000000999")
_SIGNAL_DATASET_ID = UUID("00000000-0000-0000-0000-000000000201")
_BENCHMARK_DATASET_ID = UUID("00000000-0000-0000-0000-000000000202")


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _completed_record() -> BacktestRunRecord:
    return BacktestRunRecord(
        run_id=_RUN_ID,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"long_period":3,"rsi_overbought":"90","rsi_period":2,"short_period":2}',
        symbol="005930",
        benchmark_symbol="069500",
        range_start=date(2026, 8, 3),
        range_end=date(2026, 8, 12),
        initial_cash=Decimal(1_000_000),
        signal_method="total_return",
        engine_version="backtest-1",
        cost_rule_versions='["research-krx-2026"]',
        input_bar_version_hash="c" * 64,
        action_version_hash="d" * 64,
        input_report_version_hash=None,
        signal_dataset_id=_SIGNAL_DATASET_ID,
        benchmark_dataset_id=_BENCHMARK_DATASET_ID,
        status="completed",
        failure_code=None,
        metrics=BacktestMetrics(
            total_return_pct=Decimal("-5.10"),
            pre_cost_return_pct=Decimal("-4.68"),
            benchmark_return_pct=Decimal("-10.00"),
            excess_return_pct=Decimal("4.90"),
            mdd_pct=Decimal("-6.45"),
            sharpe=Decimal("-4.7476"),
            turnover_pct=Decimal("6210.57"),
            total_fee=Decimal(389),
            total_slippage=Decimal(1949),
            total_tax=Decimal(1903),
            trade_count=2,
        ),
        created_at=_NOW,
    )


def _failed_record() -> BacktestRunRecord:
    return BacktestRunRecord(
        run_id=_FAILED_RUN_ID,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"long_period":3,"rsi_overbought":"90","rsi_period":2,"short_period":2}',
        symbol="005930",
        benchmark_symbol="069500",
        range_start=date(2026, 8, 3),
        range_end=date(2026, 8, 12),
        initial_cash=Decimal(1_000_000),
        signal_method="total_return",
        engine_version="backtest-1",
        cost_rule_versions='["research-krx-2026"]',
        input_bar_version_hash="",
        action_version_hash="",
        input_report_version_hash=None,
        signal_dataset_id=None,
        benchmark_dataset_id=None,
        status="failed",
        failure_code="missing_adjusted_dataset",
        metrics=None,
        created_at=_NOW,
    )


@final
class StubBacktestReader:
    async def runs(self, limit: int) -> tuple[BacktestRunRecord, ...]:
        _ = limit
        return (_completed_record(), _failed_record())

    async def run(self, run_id: UUID) -> BacktestRunRecord | None:
        if run_id == _RUN_ID:
            return _completed_record()
        if run_id == _FAILED_RUN_ID:
            return _failed_record()
        return None

    async def trades(self, run_id: UUID) -> tuple[BacktestTradeRecord, ...]:
        if run_id != _RUN_ID:
            return ()
        return (
            BacktestTradeRecord(
                sequence=1,
                signal_date=date(2026, 8, 7),
                execution_date=date(2026, 8, 10),
                symbol=None,
                action=SignalAction.BUY.value,
                reason=SignalReason.GOLDEN_CROSS.value,
                quantity=78,
                price=Decimal(12800),
                gross_amount=Decimal(998_400),
                fee=Decimal(199),
                slippage=Decimal(998),
                tax=Decimal(0),
                skip_reason=None,
            ),
            BacktestTradeRecord(
                sequence=2,
                signal_date=date(2026, 8, 12),
                execution_date=None,
                symbol=None,
                action=SignalAction.SELL.value,
                reason=SignalReason.DEAD_CROSS.value,
                quantity=0,
                price=None,
                gross_amount=Decimal(0),
                fee=Decimal(0),
                slippage=Decimal(0),
                tax=Decimal(0),
                skip_reason=TradeSkipReason.WINDOW_END.value,
            ),
        )

    async def equity(self, run_id: UUID) -> tuple[EquityPoint, ...]:
        if run_id != _RUN_ID:
            return ()
        return (
            EquityPoint(
                trading_date=date(2026, 8, 10),
                cash=Decimal(403),
                position_value=Decimal(1_014_000),
                nav=Decimal(1_014_403),
            ),
        )

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        backtest_reader_factory=StubBacktestReader,
    )
    return TestClient(app)


_COMPLETED_RUN_JSON: dict[str, object] = {
    "run_id": str(_RUN_ID),
    "strategy_name": "ma-rsi",
    "strategy_version": "1",
    "parameters_json": ('{"long_period":3,"rsi_overbought":"90","rsi_period":2,"short_period":2}'),
    "symbol": "005930",
    "universe_size": 0,
    "traded_symbols": [],
    "benchmark_symbol": "069500",
    "range_start": "2026-08-03",
    "range_end": "2026-08-12",
    "initial_cash": "1000000",
    "signal_method": "total_return",
    "engine_version": "backtest-1",
    "cost_rule_versions": '["research-krx-2026"]',
    "input_bar_version_hash": "c" * 64,
    "action_version_hash": "d" * 64,
    "input_report_version_hash": None,
    "signal_dataset_id": str(_SIGNAL_DATASET_ID),
    "benchmark_dataset_id": str(_BENCHMARK_DATASET_ID),
    "status": "completed",
    "failure_code": None,
    "metrics": {
        "total_return_pct": "-5.10",
        "pre_cost_return_pct": "-4.68",
        "benchmark_return_pct": "-10.00",
        "excess_return_pct": "4.90",
        "mdd_pct": "-6.45",
        "sharpe": "-4.7476",
        "turnover_pct": "6210.57",
        "total_fee": "389",
        "total_slippage": "1949",
        "total_tax": "1903",
        "trade_count": 2,
    },
    "created_at": "2026-08-18T02:00:00Z",
}
_FAILED_RUN_JSON: dict[str, object] = {
    "run_id": str(_FAILED_RUN_ID),
    "strategy_name": "ma-rsi",
    "strategy_version": "1",
    "parameters_json": ('{"long_period":3,"rsi_overbought":"90","rsi_period":2,"short_period":2}'),
    "symbol": "005930",
    "universe_size": 0,
    "traded_symbols": [],
    "benchmark_symbol": "069500",
    "range_start": "2026-08-03",
    "range_end": "2026-08-12",
    "initial_cash": "1000000",
    "signal_method": "total_return",
    "engine_version": "backtest-1",
    "cost_rule_versions": '["research-krx-2026"]',
    "input_bar_version_hash": "",
    "action_version_hash": "",
    "input_report_version_hash": None,
    "signal_dataset_id": None,
    "benchmark_dataset_id": None,
    "status": "failed",
    "failure_code": "missing_adjusted_dataset",
    "metrics": None,
    "created_at": "2026-08-18T02:00:00Z",
}


def test_backtest_runs_include_failed_runs_with_reason() -> None:
    response = _client().get("/api/backtests")

    assert response.status_code == 200
    assert response.json() == {"runs": [_COMPLETED_RUN_JSON, _FAILED_RUN_JSON]}


def test_backtest_run_detail_returns_metrics_and_lineage() -> None:
    response = _client().get(f"/api/backtests/{_RUN_ID}")

    assert response.status_code == 200
    assert response.json() == _COMPLETED_RUN_JSON


def test_backtest_trades_include_skipped_signals() -> None:
    response = _client().get(f"/api/backtests/{_RUN_ID}/trades")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(_RUN_ID),
        "trades": [
            {
                "sequence": 1,
                "symbol": None,
                "signal_date": "2026-08-07",
                "execution_date": "2026-08-10",
                "action": "buy",
                "reason": "golden_cross",
                "quantity": 78,
                "price": "12800",
                "gross_amount": "998400",
                "fee": "199",
                "slippage": "998",
                "tax": "0",
                "skip_reason": None,
            },
            {
                "sequence": 2,
                "symbol": None,
                "signal_date": "2026-08-12",
                "execution_date": None,
                "action": "sell",
                "reason": "dead_cross",
                "quantity": 0,
                "price": None,
                "gross_amount": "0",
                "fee": "0",
                "slippage": "0",
                "tax": "0",
                "skip_reason": "window_end",
            },
        ],
    }


def test_backtest_equity_returns_daily_nav() -> None:
    response = _client().get(f"/api/backtests/{_RUN_ID}/equity")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(_RUN_ID),
        "equity": [
            {
                "trading_date": "2026-08-10",
                "cash": "403",
                "position_value": "1014000",
                "nav": "1014403",
            }
        ],
    }


def test_unknown_backtest_run_returns_404() -> None:
    client = _client()
    for path in (
        f"/api/backtests/{_MISSING_RUN_ID}",
        f"/api/backtests/{_MISSING_RUN_ID}/trades",
        f"/api/backtests/{_MISSING_RUN_ID}/equity",
    ):
        response = client.get(path)
        assert response.status_code == 404


def test_invalid_run_id_returns_422() -> None:
    response = _client().get("/api/backtests/not-a-uuid")

    assert response.status_code == 422
