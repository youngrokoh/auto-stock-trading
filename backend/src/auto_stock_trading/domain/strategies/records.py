from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.domain.strategies.backtest_metrics import BacktestMetrics


@dataclass(frozen=True, slots=True)
class BacktestRunRecord:
    run_id: UUID
    strategy_name: str
    strategy_version: str
    parameters_json: str
    symbol: str
    benchmark_symbol: str
    range_start: date
    range_end: date
    initial_cash: Decimal
    signal_method: str
    engine_version: str
    cost_rule_versions: str
    input_bar_version_hash: str
    action_version_hash: str
    signal_dataset_id: UUID | None
    benchmark_dataset_id: UUID | None
    status: str
    failure_code: str | None
    metrics: BacktestMetrics | None
    created_at: datetime
