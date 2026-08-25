from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.trading_order_writes import (
    OrderTransition,
    lock_order,
    next_event_sequence,
    tracked_order,
    tracked_orders_query,
    transition_order,
    unsettled_orders_query,
)
from auto_stock_trading.adapters.database.trading_queries import (
    buy_amount_query,
    consecutive_rejects,
    open_orders_query,
    order_attempts_query,
    pending_exposure_query,
    recent_states_query,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AccountPositionRow,
    AccountSnapshotRow,
    AutomationEventRow,
    AutomationStateRow,
    OrderEventRow,
    OrderPlanRow,
    OrderRow,
    RiskDecisionRow,
)
from auto_stock_trading.adapters.database.trading_session_writes import (
    expire_order,
    read_daily_fill_totals,
)
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderState,
    next_automation_state,
)
from auto_stock_trading.domain.orders.records import (
    AutomationRecord,
    StoredAccountSnapshot,
    StoredCounters,
)
from auto_stock_trading.domain.risk.engine import PendingExposure

if TYPE_CHECKING:
    from datetime import date, datetime

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.adapters.brokers.kis_orders import BrokerAcknowledgement
    from auto_stock_trading.application.trading.planning import AutomationTransition
    from auto_stock_trading.application.trading.submission import TrackedOrder
    from auto_stock_trading.domain.market_data.models import RawBrokerResponse
    from auto_stock_trading.domain.orders.account import AccountSnapshotObservation
    from auto_stock_trading.domain.orders.fills import ReconcileProblem
    from auto_stock_trading.domain.orders.records import OrderPlanRecord, OrderRecord
    from auto_stock_trading.domain.orders.session_close import InternalDailyTotals

_SOURCE: Final = "KIS"
_OPERATION: Final = "account_balance"
_STATE_CHANGE: Final = "state_change"
_API_FAILURE: Final = "api_failure"
_SCHEDULE_BLOCKED: Final = "schedule_blocked"
_RECONCILE_PROBLEM: Final = "reconcile_problem"
_FILL_SYNC: Final = "FILL_SYNC"
_FIRST_ATTEMPT: Final = 1
_OPEN_STATES: Final = (OrderState.SUBMITTED.value, OrderState.PARTIALLY_FILLED.value)
_BUY_COUNTED_STATES: Final = (
    OrderState.PLANNED.value,
    OrderState.SUBMITTED.value,
    OrderState.PARTIALLY_FILLED.value,
    OrderState.FILLED.value,
)


def _automation_record(row: AutomationStateRow) -> AutomationRecord:
    return AutomationRecord(
        environment=row.environment,
        state=AutomationState(row.state),
        reason_code=row.reason_code,
        trading_date=row.trading_date,
        changed_at=row.changed_at,
    )


@final
class PostgresTradingStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresTradingStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresTradingStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        statement = select(AutomationStateRow).where(AutomationStateRow.environment == environment)
        async with self._sessions() as session:
            row = await session.scalar(statement)
        return None if row is None else _automation_record(row)

    async def transition_automation(
        self,
        transition: AutomationTransition,
    ) -> AutomationRecord:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(AutomationStateRow).where(
                    AutomationStateRow.environment == transition.environment
                )
            )
            current = AutomationState.DISABLED if row is None else AutomationState(row.state)
            requested = next_automation_state(current, transition.requested)
            if row is None:
                session.add(
                    AutomationStateRow(
                        id=uuid4(),
                        environment=transition.environment,
                        state=requested.value,
                        reason_code=transition.reason_code,
                        trading_date=transition.trading_date,
                        changed_at=transition.occurred_at,
                    )
                )
            else:
                _ = await session.execute(
                    update(AutomationStateRow)
                    .where(AutomationStateRow.id == row.id)
                    .values(
                        state=requested.value,
                        reason_code=transition.reason_code,
                        trading_date=transition.trading_date,
                        changed_at=transition.occurred_at,
                    )
                )
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=transition.environment,
                    event_type=_STATE_CHANGE,
                    previous_state=current.value,
                    state=requested.value,
                    reason_code=transition.reason_code,
                    detail=None,
                    occurred_at=transition.occurred_at,
                )
            )
        return AutomationRecord(
            environment=transition.environment,
            state=requested,
            reason_code=transition.reason_code,
            trading_date=transition.trading_date,
            changed_at=transition.occurred_at,
        )

    async def record_schedule_block(
        self,
        environment: str,
        block_code: str,
        occurred_at: datetime,
    ) -> None:
        """예약 제출이 차단된 사실(ADR-0015 결정 6).

        사람이 없는 경로에서는 차단이 저장되지 않으면 '아무 주문도 없던 날'과 구분되지 않는다.
        사유는 `reason_code`에 남겨 알림 선별이 그대로 읽는다.
        """
        async with self._sessions.begin() as session:
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=environment,
                    event_type=_SCHEDULE_BLOCKED,
                    previous_state=None,
                    state=None,
                    reason_code=block_code[:40],
                    detail=None,
                    occurred_at=occurred_at,
                )
            )

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=environment,
                    event_type=_API_FAILURE,
                    previous_state=None,
                    state=None,
                    reason_code=None,
                    detail=detail[:500],
                    occurred_at=occurred_at,
                )
            )

    async def api_failures_since(self, environment: str, since: datetime) -> int:
        statement = (
            select(func.count())
            .select_from(AutomationEventRow)
            .where(
                AutomationEventRow.environment == environment,
                AutomationEventRow.event_type == _API_FAILURE,
                AutomationEventRow.occurred_at >= since,
            )
        )
        async with self._sessions() as session:
            return await session.scalar(statement) or 0

    async def save_account_snapshot(
        self,
        observation: AccountSnapshotObservation,
    ) -> StoredAccountSnapshot:
        snapshot = observation.snapshot
        snapshot_id = uuid4()
        raw_id = uuid4()
        async with self._sessions.begin() as session:
            session.add(
                RawApiResponseRow(
                    id=raw_id,
                    source=_SOURCE,
                    operation=_OPERATION,
                    endpoint=observation.raw.endpoint,
                    request_fingerprint=observation.raw.request_fingerprint,
                    received_at=observation.raw.received_at,
                    payload_json=observation.raw.payload_json,
                )
            )
            session.add(
                AccountSnapshotRow(
                    id=snapshot_id,
                    source=snapshot.source,
                    environment=snapshot.environment,
                    account_reference=snapshot.account_reference,
                    currency=snapshot.currency,
                    cash_balance=snapshot.cash_balance,
                    orderable_cash=snapshot.orderable_cash,
                    position_value=snapshot.position_value,
                    nav=snapshot.nav,
                    broker_position_value=snapshot.broker_position_value,
                    broker_net_asset=snapshot.broker_net_asset,
                    trading_date=snapshot.trading_date,
                    as_of=snapshot.as_of,
                    received_at=snapshot.received_at,
                    raw_response_id=raw_id,
                    created_at=snapshot.received_at,
                )
            )
            await session.flush()
            for position in snapshot.positions:
                instrument_id = await _instrument_id(session, position.symbol)
                session.add(
                    AccountPositionRow(
                        id=uuid4(),
                        snapshot_id=snapshot_id,
                        instrument_id=instrument_id,
                        quantity=position.quantity,
                        orderable_quantity=position.orderable_quantity,
                        average_price=position.average_price,
                        current_price=position.current_price,
                        evaluation_amount=position.evaluation_amount,
                        profit_loss=position.profit_loss,
                    )
                )
        return StoredAccountSnapshot(snapshot_id=snapshot_id, snapshot=snapshot)

    async def session_open_nav(self, environment: str, trading_date: date) -> Decimal | None:
        statement = (
            select(AccountSnapshotRow.nav)
            .where(
                AccountSnapshotRow.environment == environment,
                AccountSnapshotRow.trading_date == trading_date,
            )
            .order_by(AccountSnapshotRow.received_at)
            .limit(1)
        )
        async with self._sessions() as session:
            return await session.scalar(statement)

    async def peak_nav(self, environment: str) -> Decimal | None:
        statement = select(func.max(AccountSnapshotRow.nav)).where(
            AccountSnapshotRow.environment == environment
        )
        async with self._sessions() as session:
            return await session.scalar(statement)

    async def counters(self, environment: str, trading_date: date) -> StoredCounters:
        async with self._sessions() as session:
            open_orders = await session.scalar(open_orders_query(environment))
            attempts = await session.scalar(order_attempts_query(environment, trading_date))
            buy_amount = await session.scalar(buy_amount_query(environment, trading_date))
            recent_states = (await session.scalars(recent_states_query(environment))).all()
        return StoredCounters(
            open_orders=open_orders or 0,
            daily_order_attempts=attempts or 0,
            daily_buy_amount=Decimal(buy_amount or 0),
            consecutive_rejects=consecutive_rejects(recent_states),
            unreconciled_orders=bool(open_orders),
        )

    async def pending_orders(
        self,
        environment: str,
        trading_date: date,
        plan_id: UUID | None,
    ) -> tuple[TrackedOrder, ...]:
        """제출 대상은 그 거래일 계획의 `planned` 주문뿐이다."""
        statement = tracked_orders_query(environment, trading_date).where(
            OrderRow.state == OrderState.PLANNED.value
        )
        if plan_id is not None:
            statement = statement.where(OrderRow.plan_id == plan_id)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(tracked_order(row, symbol, plan) for row, symbol, plan in rows)

    async def open_orders(
        self,
        environment: str,
        trading_date: date,
    ) -> tuple[TrackedOrder, ...]:
        statement = tracked_orders_query(environment, trading_date).where(
            OrderRow.state.in_(_OPEN_STATES)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(tracked_order(row, symbol, plan) for row, symbol, plan in rows)

    async def record_submission(
        self,
        order_id: UUID,
        acknowledgement: BrokerAcknowledgement,
        submitted_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await _save_raw(session, acknowledgement.raw)
            await transition_order(
                session,
                OrderTransition(
                    order_id=order_id,
                    state=OrderState.SUBMITTED,
                    reason_code=acknowledgement.message_code,
                    occurred_at=submitted_at,
                    values={
                        "broker_order_id": acknowledgement.broker_order_id,
                        "broker_org_no": acknowledgement.broker_org_no,
                        "broker_order_time": acknowledgement.broker_order_time,
                        "submitted_at": submitted_at,
                    },
                ),
            )

    async def record_rejection(
        self,
        order_id: UUID,
        acknowledgement: BrokerAcknowledgement,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await _save_raw(session, acknowledgement.raw)
            await transition_order(
                session,
                OrderTransition(
                    order_id=order_id,
                    state=OrderState.REJECTED,
                    reason_code=acknowledgement.message_code,
                    occurred_at=occurred_at,
                    values={"reject_code": acknowledgement.message_code},
                ),
            )

    async def apply_fill(
        self,
        order_id: UUID,
        state: OrderState,
        filled_quantity: int,
        average_fill_price: Decimal | None,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await transition_order(
                session,
                OrderTransition(
                    order_id=order_id,
                    state=state,
                    reason_code=_FILL_SYNC,
                    occurred_at=occurred_at,
                    values={
                        "filled_quantity": filled_quantity,
                        "average_fill_price": average_fill_price,
                    },
                ),
            )

    async def unsettled_orders(self, environment: str) -> tuple[TrackedOrder, ...]:
        """거래일과 무관하게 미종결인 주문. 리스너 부착 검사와 잔재 판정이 쓴다(ADR-0017 결정 5)."""
        statement = unsettled_orders_query(environment)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(tracked_order(row, symbol, plan) for row, symbol, plan in rows)

    async def expire_order(
        self,
        order_id: UUID,
        evidence: str,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await expire_order(session, order_id, evidence, occurred_at)

    async def daily_fill_totals(
        self,
        environment: str,
        trading_date: date,
    ) -> InternalDailyTotals:
        async with self._sessions() as session:
            return await read_daily_fill_totals(session, environment, trading_date)

    async def record_order_event(
        self,
        order_id: UUID,
        event_type: str,
        detail: str | None,
        occurred_at: datetime,
    ) -> None:
        """상태를 바꾸지 않는 주문 이벤트(취소 요청·실패)를 append-only로 남긴다."""
        async with self._sessions.begin() as session:
            current = await lock_order(session, order_id)
            session.add(
                OrderEventRow(
                    id=uuid4(),
                    order_id=order_id,
                    sequence=await next_event_sequence(session, order_id),
                    previous_state=current.state,
                    state=current.state,
                    reason_code=event_type,
                    detail=detail,
                    occurred_at=occurred_at,
                )
            )

    async def save_broker_response(self, raw: RawBrokerResponse) -> None:
        """조회·취소 응답 원본을 append-only로 남긴다. 정규화 상태와 분리한다."""
        async with self._sessions.begin() as session:
            await _save_raw(session, raw)

    async def record_reconcile_problem(
        self,
        environment: str,
        broker_order_id: str,
        problem: ReconcileProblem,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=environment,
                    event_type=_RECONCILE_PROBLEM,
                    previous_state=None,
                    state=None,
                    reason_code=problem.value,
                    detail=broker_order_id,
                    occurred_at=occurred_at,
                )
            )

    async def pending_exposure(
        self,
        environment: str,
        trading_date: date,
        exclude_order_id: UUID | None = None,
    ) -> tuple[PendingExposure, ...]:
        """정정 판정에서는 대상 주문 자신을 제외해야 자기 노출을 두 번 세지 않는다."""
        statement = pending_exposure_query(environment, trading_date)
        if exclude_order_id is not None:
            statement = statement.where(OrderRow.id != exclude_order_id)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(
            PendingExposure(symbol=symbol, amount=Decimal(amount)) for symbol, amount in rows
        )

    async def withdraw_planned_orders(
        self,
        plan_id: UUID,
        reason_code: str,
        occurred_at: datetime,
    ) -> int:
        """제출 전 계획 주문을 철회한다(상태 그래프의 PLANNED → CANCELED). 이력은 보존된다."""
        async with self._sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(OrderRow.id).where(
                        OrderRow.plan_id == plan_id,
                        OrderRow.state == OrderState.PLANNED.value,
                    )
                )
            ).all()
            for order_id in rows:
                await transition_order(
                    session,
                    OrderTransition(
                        order_id=order_id,
                        state=OrderState.CANCELED,
                        reason_code=reason_code,
                        occurred_at=occurred_at,
                        values={},
                    ),
                )
        return len(rows)

    async def save_plan(self, plan: OrderPlanRecord) -> None:
        async with self._sessions.begin() as session:
            session.add(
                OrderPlanRow(
                    id=plan.plan_id,
                    environment=plan.environment,
                    strategy_name=plan.strategy_name,
                    strategy_version=plan.strategy_version,
                    parameters_json=plan.parameters_json,
                    signal_date=plan.signal_date,
                    trading_date=plan.trading_date,
                    account_snapshot_id=plan.account_snapshot_id,
                    nav_basis=plan.nav_basis,
                    session_open_nav=plan.session_open_nav,
                    automation_state=plan.automation_state.value,
                    status=plan.status,
                    block_code=plan.block_code,
                    planned_at=plan.planned_at,
                    created_at=plan.planned_at,
                )
            )
            await session.flush()
            for order in plan.orders:
                await _save_order(session, plan, order)

    async def stored_order_count(self, plan_id: UUID) -> int:
        """그 계획에 실제로 저장된 주문 수. 중복 식별자로 생략된 주문은 세지 않는다."""
        statement = select(func.count()).select_from(OrderRow).where(OrderRow.plan_id == plan_id)
        async with self._sessions() as session:
            return await session.scalar(statement) or 0

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


async def _save_raw(session: AsyncSession, raw: RawBrokerResponse) -> None:
    session.add(
        RawApiResponseRow(
            id=uuid4(),
            source=_SOURCE,
            operation=raw.operation.value,
            endpoint=raw.endpoint,
            request_fingerprint=raw.request_fingerprint,
            received_at=raw.received_at,
            payload_json=raw.payload_json,
        )
    )


async def _instrument_id(session: AsyncSession, symbol: str) -> UUID:
    instrument_id = await session.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == symbol).limit(1)
    )
    if instrument_id is None:
        message = f"unknown instrument {symbol}"
        raise LookupError(message)
    return instrument_id


async def _save_order(
    session: AsyncSession,
    plan: OrderPlanRecord,
    order: OrderRecord,
) -> None:
    instrument_id = await _instrument_id(session, order.symbol)
    order_id = uuid4()
    inserted = await session.scalar(
        insert(OrderRow)
        .values(
            id=order_id,
            plan_id=plan.plan_id,
            client_order_id=order.client_order_id,
            instrument_id=instrument_id,
            sequence=order.sequence,
            side=order.side.value,
            order_type=order.order_type.value,
            quantity=order.quantity,
            filled_quantity=0,
            limit_price=order.limit_price,
            reference_price=order.reference_price,
            reference_source=order.reference_source,
            reference_received_at=order.reference_received_at,
            state=order.state.value,
            reject_code=order.reject_code,
            broker_order_id=None,
            revision_count=0,
            created_at=plan.planned_at,
            updated_at=plan.planned_at,
        )
        .on_conflict_do_nothing(constraint="uq_order_client_order_id")
        .returning(OrderRow.id)
    )
    if inserted is None:
        return
    session.add(
        OrderEventRow(
            id=uuid4(),
            order_id=order_id,
            sequence=1,
            previous_state=None,
            state=order.state.value,
            reason_code=order.reject_code,
            detail=None,
            occurred_at=plan.planned_at,
        )
    )
    for decision in order.decisions:
        session.add(
            RiskDecisionRow(
                id=uuid4(),
                order_id=order_id,
                rule_code=decision.rule.value,
                attempt=_FIRST_ATTEMPT,
                limit_value=decision.limit_value,
                projected_value=decision.projected_value,
                passed=decision.passed,
            )
        )
