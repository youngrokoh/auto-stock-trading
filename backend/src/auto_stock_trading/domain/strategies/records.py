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
    # 다종목 실행은 대표 종목이 없다. 유니버스와 실제 매매된 종목으로 식별한다.
    symbol: str | None
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
    # 다종목 실행에서만 채워진다. 단일 종목 실행은 비어 있다.
    universe: tuple[str, ...] = ()
    traded_symbols: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioRunRecord:
    """다종목 실행 기록. 대표 종목이 없으므로 유니버스를 행으로 보존한다(계약 v2)."""

    run_id: UUID
    strategy_name: str
    strategy_version: str
    parameters_json: str
    universe: tuple[str, ...]
    benchmark_symbol: str
    range_start: date
    range_end: date
    initial_cash: Decimal
    signal_method: str
    engine_version: str
    cost_rule_versions: str
    input_bar_version_hash: str
    action_version_hash: str
    benchmark_dataset_id: UUID | None
    status: str
    failure_code: str | None
    metrics: BacktestMetrics | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BacktestTradeRecord:
    """조회용 체결 기록.

    `action`·`reason`·`skip_reason`은 저장된 감사 문자열 그대로 둔다. 전략마다 사유 어휘가
    다르므로 읽기 경로가 한 전략의 enum으로 되검증하면 다른 전략의 실행 조회가 깨진다
    (2026-08-21 실측: 다종목 실행의 체결 목록이 `rebalance` 때문에 500이 됐다).
    """

    sequence: int
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
