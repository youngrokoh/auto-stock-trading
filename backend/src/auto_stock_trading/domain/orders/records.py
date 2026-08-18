from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.domain.orders.account import AccountSnapshot
    from auto_stock_trading.domain.orders.models import (
        AutomationState,
        OrderSide,
        OrderState,
        OrderType,
    )
    from auto_stock_trading.domain.risk.engine import RiskDecision


@dataclass(frozen=True, slots=True)
class OrderRecord:
    client_order_id: str
    sequence: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None
    reference_price: Decimal | None
    reference_source: str | None
    reference_received_at: datetime | None
    state: OrderState
    reject_code: str | None
    decisions: tuple[RiskDecision, ...]


@dataclass(frozen=True, slots=True)
class OrderPlanRecord:
    plan_id: UUID
    environment: str
    strategy_name: str
    strategy_version: str
    parameters_json: str
    signal_date: date
    trading_date: date
    account_snapshot_id: UUID | None
    nav_basis: Decimal | None
    session_open_nav: Decimal | None
    automation_state: AutomationState
    status: str
    block_code: str | None
    planned_at: datetime
    orders: tuple[OrderRecord, ...]


@dataclass(frozen=True, slots=True)
class StoredCounters:
    open_orders: int
    daily_order_attempts: int
    daily_buy_amount: Decimal
    consecutive_rejects: int
    unreconciled_orders: bool


@dataclass(frozen=True, slots=True)
class AutomationRecord:
    environment: str
    state: AutomationState
    reason_code: str | None
    trading_date: date | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class AutomationEventRecord:
    event_type: str
    previous_state: AutomationState | None
    state: AutomationState | None
    reason_code: str | None
    detail: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class StoredAccountSnapshot:
    snapshot_id: UUID
    snapshot: AccountSnapshot


@dataclass(frozen=True, slots=True)
class OrderPlanSummary:
    plan: OrderPlanRecord
    order_count: int
    rejected_count: int


@dataclass(frozen=True, slots=True)
class OrderListEntry:
    """계획 경계를 넘어 시간순으로 나열되는 주문 한 건. 위험검사 판정은 계획 상세에서 조회한다."""

    client_order_id: str
    plan_id: UUID
    trading_date: date
    created_at: datetime
    sequence: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    filled_quantity: int
    limit_price: Decimal | None
    reference_price: Decimal | None
    reference_source: str | None
    reference_received_at: datetime | None
    state: OrderState
    reject_code: str | None


@dataclass(frozen=True, slots=True)
class TradingRiskState:
    """위험 한도 소진율 계산의 입력이 되는 현재 상태."""

    evaluated_at: datetime
    basis_date: date | None
    snapshot: StoredAccountSnapshot | None
    session_open_nav: Decimal | None
    peak_nav: Decimal | None
    max_order_amount: Decimal
    counters: StoredCounters
    api_failures: int
