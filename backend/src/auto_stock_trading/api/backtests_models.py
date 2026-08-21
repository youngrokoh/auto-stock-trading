from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BacktestResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class BacktestMetricsResponse(BacktestResponse):
    total_return_pct: Decimal
    pre_cost_return_pct: Decimal
    benchmark_return_pct: Decimal
    excess_return_pct: Decimal
    mdd_pct: Decimal
    sharpe: Decimal | None
    turnover_pct: Decimal
    total_fee: Decimal
    total_slippage: Decimal
    total_tax: Decimal
    trade_count: int


class BacktestRunResponse(BacktestResponse):
    run_id: UUID
    strategy_name: str
    strategy_version: str
    parameters_json: str
    # 다종목 실행은 대표 종목이 없다. 유니버스·매매 종목으로 식별한다.
    symbol: str | None
    universe_size: int
    traded_symbols: tuple[str, ...]
    benchmark_symbol: str
    range_start: date
    range_end: date
    initial_cash: Decimal
    signal_method: str
    engine_version: str
    cost_rule_versions: str
    input_bar_version_hash: str
    action_version_hash: str
    input_report_version_hash: str | None
    signal_dataset_id: UUID | None
    benchmark_dataset_id: UUID | None
    status: str
    failure_code: str | None
    metrics: BacktestMetricsResponse | None
    created_at: datetime


class BacktestRunsResponse(BacktestResponse):
    runs: tuple[BacktestRunResponse, ...]


class BacktestTradeResponse(BacktestResponse):
    sequence: int
    # 다종목 실행의 체결은 종목을 갖는다. 단일 종목 실행은 실행의 종목과 같아 비어 있다.
    symbol: str | None
    signal_date: date
    execution_date: date | None
    action: str
    reason: str
    quantity: int
    price: Decimal | None
    gross_amount: Decimal
    fee: Decimal
    slippage: Decimal
    tax: Decimal
    skip_reason: str | None


class BacktestTradesResponse(BacktestResponse):
    run_id: UUID
    trades: tuple[BacktestTradeResponse, ...]


class BacktestEquityPointResponse(BacktestResponse):
    trading_date: date
    cash: Decimal
    position_value: Decimal
    nav: Decimal


class BacktestEquityResponse(BacktestResponse):
    run_id: UUID
    equity: tuple[BacktestEquityPointResponse, ...]
