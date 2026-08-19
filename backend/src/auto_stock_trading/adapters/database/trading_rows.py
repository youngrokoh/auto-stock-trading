from datetime import date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class AccountSnapshotRow(Base):
    __tablename__: str = "account_snapshot"
    __table_args__: tuple[dict[str, str]] = ({"schema": "trading"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    environment: Mapped[str] = mapped_column(String(8), index=True)
    account_reference: Mapped[str] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(3))
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    orderable_cash: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    position_value: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    nav: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    broker_net_asset: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    trading_date: Mapped[date] = mapped_column(Date)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(ForeignKey("operations.raw_api_response.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class AccountPositionRow(Base):
    __tablename__: str = "account_position"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("snapshot_id", "instrument_id", name="uq_account_position_snapshot"),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading.account_snapshot.id", ondelete="CASCADE"),
        index=True,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
    )
    quantity: Mapped[int] = mapped_column(Integer)
    orderable_quantity: Mapped[int] = mapped_column(Integer)
    average_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    current_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    evaluation_amount: Mapped[Decimal] = mapped_column(Numeric(24, 0))
    profit_loss: Mapped[Decimal] = mapped_column(Numeric(24, 0))


@final
class AutomationStateRow(Base):
    __tablename__: str = "automation_state"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("environment", name="uq_automation_state_environment"),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8))
    state: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    trading_date: Mapped[date | None] = mapped_column(Date)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class AutomationEventRow(Base):
    __tablename__: str = "automation_event"
    __table_args__: tuple[dict[str, str]] = ({"schema": "trading"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8), index=True)
    event_type: Mapped[str] = mapped_column(String(24))
    previous_state: Mapped[str | None] = mapped_column(String(16))
    state: Mapped[str | None] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@final
class OrderPlanRow(Base):
    __tablename__: str = "order_plan"
    __table_args__: tuple[dict[str, str]] = ({"schema": "trading"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8), index=True)
    strategy_name: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(16))
    parameters_json: Mapped[str] = mapped_column(Text)
    signal_date: Mapped[date] = mapped_column(Date)
    trading_date: Mapped[date] = mapped_column(Date)
    account_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading.account_snapshot.id", ondelete="SET NULL"),
    )
    nav_basis: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    session_open_nav: Mapped[Decimal | None] = mapped_column(Numeric(24, 0))
    automation_state: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    block_code: Mapped[str | None] = mapped_column(String(40))
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class OrderRow(Base):
    __tablename__: str = "order"
    __table_args__: tuple[UniqueConstraint, UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("client_order_id", name="uq_order_client_order_id"),
        UniqueConstraint("plan_id", "sequence", name="uq_order_plan_sequence"),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading.order_plan.id", ondelete="CASCADE"),
        index=True,
    )
    client_order_id: Mapped[str] = mapped_column(String(32))
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
    )
    sequence: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    reference_source: Mapped[str | None] = mapped_column(String(32))
    reference_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20), index=True)
    reject_code: Mapped[str | None] = mapped_column(String(40))
    broker_order_id: Mapped[str | None] = mapped_column(String(40))
    broker_org_no: Mapped[str | None] = mapped_column(String(8))
    broker_order_time: Mapped[str | None] = mapped_column(String(6))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class OrderEventRow(Base):
    __tablename__: str = "order_event"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("order_id", "sequence", name="uq_order_event_sequence"),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading.order.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    previous_state: Mapped[str | None] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class FillNotificationRow(Base):
    """실시간 체결통보 한 건. 본문은 계약의 마스킹 규칙을 지난 뒤에만 저장된다."""

    __tablename__: str = "fill_notification"
    __table_args__: tuple[dict[str, str]] = ({"schema": "trading"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8))
    account_reference: Mapped[str] = mapped_column(String(12))
    order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading.order.id", ondelete="SET NULL"),
    )
    broker_order_id: Mapped[str] = mapped_column(String(40))
    original_broker_order_id: Mapped[str | None] = mapped_column(String(40))
    notification_kind: Mapped[str] = mapped_column(String(12))
    side: Mapped[str] = mapped_column(String(4))
    symbol: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    order_quantity: Mapped[int] = mapped_column(Integer)
    broker_event_time: Mapped[str] = mapped_column(String(6))
    rejected: Mapped[bool] = mapped_column(Boolean)
    revise_code: Mapped[str] = mapped_column(String(4))
    accept_code: Mapped[str] = mapped_column(String(4))
    branch_no: Mapped[str] = mapped_column(String(8))
    masked_payload: Mapped[str] = mapped_column(Text)
    problem: Mapped[str | None] = mapped_column(String(40))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class NotificationSessionRow(Base):
    """체결통보 리스너 세션. 제출 게이트가 이 행의 심박을 본다."""

    __tablename__: str = "notification_session"
    __table_args__: tuple[dict[str, str]] = ({"schema": "trading"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8))
    transaction_id: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(12))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnect_reason: Mapped[str | None] = mapped_column(String(40))


@final
class RiskDecisionRow(Base):
    __tablename__: str = "risk_decision"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("order_id", "rule_code", name="uq_risk_decision_rule"),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading.order.id", ondelete="CASCADE"),
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(40))
    limit_value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    projected_value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    passed: Mapped[bool] = mapped_column(Boolean)
