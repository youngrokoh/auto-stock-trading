from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    from auto_stock_trading.domain.orders.account import AccountSnapshot
    from auto_stock_trading.domain.orders.fills import ReconcileProblem
    from auto_stock_trading.domain.orders.models import (
        AutomationState,
        OrderSide,
        OrderState,
        OrderType,
    )
    from auto_stock_trading.domain.orders.notifications import FillNotification
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
    # 실제로 저장된 주문 수. 같은 신호를 다시 계획하면 `client_order_id` 중복으로 저장이 생략되므로
    # 엔진이 만든 수와 다를 수 있다. 저장 전에는 비어 있다.
    stored_orders: int | None = None


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
    broker_order_id: str | None
    submitted_at: datetime | None
    average_fill_price: Decimal | None


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
    # 보유 종목의 업종 키. 비어 있으면 업종 사실이 아직 없다는 뜻이다.
    sectors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class FillNotificationRecord:
    """저장할 체결통보 한 건. 상태 전이 목표를 함께 담아 같은 트랜잭션에서 반영한다."""

    environment: str
    account_reference: str
    order_id: UUID | None
    notification: FillNotification
    masked_payload: str
    problem: ReconcileProblem | None
    state: OrderState | None
    # 부분 취소 후의 주문 수량(취소량이 아니다). 수량이 바뀌지 않는 통보는 `None`이다.
    quantity: int | None
    filled_quantity: int | None
    average_fill_price: Decimal | None
    received_at: datetime


@dataclass(frozen=True, slots=True)
class AttestationTarget:
    """사람이 확인해 종결할 주문의 현재 상태. 제출 시각이 적용 범위 판정에 쓰인다."""

    order_id: UUID
    client_order_id: str
    symbol: str
    quantity: int
    filled_quantity: int
    average_fill_price: Decimal | None
    state: OrderState
    submitted_at: datetime | None
