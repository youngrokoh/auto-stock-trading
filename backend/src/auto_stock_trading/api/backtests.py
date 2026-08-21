from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from auto_stock_trading.api.backtests_models import (
    BacktestEquityPointResponse,
    BacktestEquityResponse,
    BacktestMetricsResponse,
    BacktestRunResponse,
    BacktestRunsResponse,
    BacktestTradeResponse,
    BacktestTradesResponse,
)

if TYPE_CHECKING:
    from auto_stock_trading.application.backtests.reader import BacktestReader
    from auto_stock_trading.domain.strategies.backtest_metrics import (
        BacktestMetrics,
        EquityPoint,
    )
    from auto_stock_trading.domain.strategies.records import BacktestRunRecord, BacktestTradeRecord


def _metrics_response(metrics: BacktestMetrics | None) -> BacktestMetricsResponse | None:
    if metrics is None:
        return None
    return BacktestMetricsResponse(
        total_return_pct=metrics.total_return_pct,
        pre_cost_return_pct=metrics.pre_cost_return_pct,
        benchmark_return_pct=metrics.benchmark_return_pct,
        excess_return_pct=metrics.excess_return_pct,
        mdd_pct=metrics.mdd_pct,
        sharpe=metrics.sharpe,
        turnover_pct=metrics.turnover_pct,
        total_fee=metrics.total_fee,
        total_slippage=metrics.total_slippage,
        total_tax=metrics.total_tax,
        trade_count=metrics.trade_count,
    )


def _run_response(record: BacktestRunRecord) -> BacktestRunResponse:
    return BacktestRunResponse(
        run_id=record.run_id,
        strategy_name=record.strategy_name,
        strategy_version=record.strategy_version,
        parameters_json=record.parameters_json,
        symbol=record.symbol,
        universe_size=len(record.universe),
        traded_symbols=record.traded_symbols,
        benchmark_symbol=record.benchmark_symbol,
        range_start=record.range_start,
        range_end=record.range_end,
        initial_cash=record.initial_cash,
        signal_method=record.signal_method,
        engine_version=record.engine_version,
        cost_rule_versions=record.cost_rule_versions,
        input_bar_version_hash=record.input_bar_version_hash,
        action_version_hash=record.action_version_hash,
        input_report_version_hash=record.input_report_version_hash,
        signal_dataset_id=record.signal_dataset_id,
        benchmark_dataset_id=record.benchmark_dataset_id,
        status=record.status,
        failure_code=record.failure_code,
        metrics=_metrics_response(record.metrics),
        created_at=record.created_at,
    )


def _trade_response(trade: BacktestTradeRecord) -> BacktestTradeResponse:
    return BacktestTradeResponse(
        sequence=trade.sequence,
        symbol=trade.symbol,
        signal_date=trade.signal_date,
        execution_date=trade.execution_date,
        action=trade.action,
        reason=trade.reason,
        quantity=trade.quantity,
        price=trade.price,
        gross_amount=trade.gross_amount,
        fee=trade.fee,
        slippage=trade.slippage,
        tax=trade.tax,
        skip_reason=trade.skip_reason,
    )


def _equity_response(point: EquityPoint) -> BacktestEquityPointResponse:
    return BacktestEquityPointResponse(
        trading_date=point.trading_date,
        cash=point.cash,
        position_value=point.position_value,
        nav=point.nav,
    )


def create_backtests_router(backtests: BacktestReader) -> APIRouter:
    router = APIRouter(prefix="/api/backtests", tags=["backtests"])

    async def run_list(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> BacktestRunsResponse:
        records = await backtests.runs(limit)
        return BacktestRunsResponse(runs=tuple(_run_response(record) for record in records))

    async def run_detail(run_id: UUID) -> BacktestRunResponse:
        record = await backtests.run(run_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "backtest run not found")
        return _run_response(record)

    async def run_trades(run_id: UUID) -> BacktestTradesResponse:
        record = await backtests.run(run_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "backtest run not found")
        trades = await backtests.trades(run_id)
        return BacktestTradesResponse(
            run_id=run_id,
            trades=tuple(_trade_response(trade) for trade in trades),
        )

    async def run_equity(run_id: UUID) -> BacktestEquityResponse:
        record = await backtests.run(run_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "backtest run not found")
        equity = await backtests.equity(run_id)
        return BacktestEquityResponse(
            run_id=run_id,
            equity=tuple(_equity_response(point) for point in equity),
        )

    router.add_api_route(
        "",
        run_list,
        methods=["GET"],
        description=(
            "저장된 백테스트 실행 기록을 최신 순으로 반환한다. 실패한 실행도 사유 코드와 함께 "
            "포함되며, 각 실행은 전략·파라미터·입력 데이터 계보(일봉 버전 해시, 기업행사 버전 "
            "해시, 수정주가 데이터셋 ID)와 비용 규칙 버전을 항상 포함한다."
        ),
    )
    router.add_api_route(
        "/{run_id}",
        run_detail,
        methods=["GET"],
        description="백테스트 실행 하나의 상세와 성과 지표를 반환한다.",
    )
    router.add_api_route(
        "/{run_id}/trades",
        run_trades,
        methods=["GET"],
        description=(
            "실행의 신호별 체결 기록을 순번대로 반환한다. 체결하지 못한 신호는 "
            "skip_reason과 함께 남는다."
        ),
    )
    router.add_api_route(
        "/{run_id}/equity",
        run_equity,
        methods=["GET"],
        description="실행의 일별 현금·평가액·NAV 곡선을 반환한다.",
    )
    return router
