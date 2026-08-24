from datetime import date, datetime, time
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TradingResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class AutomationEventResponse(TradingResponse):
    event_type: str
    previous_state: str | None
    state: str | None
    reason_code: str | None
    detail: str | None
    occurred_at: datetime


class AutomationResponse(TradingResponse):
    environment: str
    # 지금 동작을 지배하는 상태. 저장된 값이 지난 거래일이면 정책 §6대로 `disabled`다.
    state: str
    # 저장된 사실 그대로. 조회는 기록을 고쳐 쓰지 않는다.
    stored_state: str
    # 저장값과 다르게 판정한 사유. 같으면 `null`이다.
    stale_reason_code: str | None
    reason_code: str | None
    trading_date: date | None
    changed_at: datetime | None
    events: tuple[AutomationEventResponse, ...]


class AccountPositionResponse(TradingResponse):
    symbol: str
    quantity: int
    orderable_quantity: int
    average_price: Decimal
    current_price: Decimal
    evaluation_amount: Decimal
    profit_loss: Decimal


class AccountSnapshotResponse(TradingResponse):
    snapshot_id: UUID
    source: str
    environment: str
    account_reference: str
    currency: str
    cash_balance: Decimal
    orderable_cash: Decimal
    position_value: Decimal
    nav: Decimal
    broker_net_asset: Decimal
    trading_date: date
    as_of: datetime
    received_at: datetime
    positions: tuple[AccountPositionResponse, ...]


class AccountSnapshotsResponse(TradingResponse):
    environment: str
    snapshots: tuple[AccountSnapshotResponse, ...]


class RiskDecisionResponse(TradingResponse):
    rule_code: str
    limit_value: Decimal
    projected_value: Decimal
    passed: bool


class OrderResponse(TradingResponse):
    client_order_id: str
    sequence: int
    symbol: str
    side: str
    order_type: str
    quantity: int
    limit_price: Decimal | None
    reference_price: Decimal | None
    reference_source: str | None
    reference_received_at: datetime | None
    state: str
    reject_code: str | None
    risk_decisions: tuple[RiskDecisionResponse, ...]


class OrderPlanResponse(TradingResponse):
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
    automation_state: str
    status: str
    block_code: str | None
    planned_at: datetime
    orders: tuple[OrderResponse, ...]


class OrderPlanSummaryResponse(TradingResponse):
    plan_id: UUID
    strategy_name: str
    strategy_version: str
    signal_date: date
    trading_date: date
    automation_state: str
    status: str
    block_code: str | None
    planned_at: datetime
    order_count: int
    rejected_count: int


class OrderPlansResponse(TradingResponse):
    environment: str
    plans: tuple[OrderPlanSummaryResponse, ...]


class OrderListEntryResponse(TradingResponse):
    client_order_id: str
    plan_id: UUID
    trading_date: date
    created_at: datetime
    sequence: int
    symbol: str
    side: str
    order_type: str
    quantity: int
    filled_quantity: int
    limit_price: Decimal | None
    reference_price: Decimal | None
    reference_source: str | None
    reference_received_at: datetime | None
    state: str
    reject_code: str | None
    broker_order_id: str | None
    submitted_at: datetime | None
    average_fill_price: Decimal | None


class OrdersResponse(TradingResponse):
    environment: str
    orders: tuple[OrderListEntryResponse, ...]


class NotificationEntryResponse(TradingResponse):
    """최근 알림 한 건. 본문은 담지 않는다 — 현황만 본다."""

    kind: str
    severity: str
    state: str
    attempts: int
    reason: str | None
    event_occurred_at: datetime


class NotificationStatusResponse(TradingResponse):
    """외부 알림 발신 현황(ADR-0014 결정 4)."""

    environment: str
    pending: int
    failed: int
    sent_today: int
    oldest_pending_at: datetime | None
    recent: tuple[NotificationEntryResponse, ...]


class RiskLimitUsageResponse(TradingResponse):
    rule_code: str
    basis: str
    comparison: str
    limit_value: Decimal
    current_value: Decimal | None
    usage_ratio: Decimal | None
    reason: str | None


class OrderConditionsResponse(TradingResponse):
    order_window_start: time
    order_window_end: time
    quote_max_age_seconds: int
    price_band: Decimal
    api_failure_window_seconds: int


class RiskLimitsResponse(TradingResponse):
    environment: str
    evaluated_at: datetime
    basis_date: date | None
    snapshot_id: UUID | None
    snapshot_as_of: datetime | None
    nav_basis: Decimal | None
    session_open_nav: Decimal | None
    peak_nav: Decimal | None
    items: tuple[RiskLimitUsageResponse, ...]
    conditions: OrderConditionsResponse
