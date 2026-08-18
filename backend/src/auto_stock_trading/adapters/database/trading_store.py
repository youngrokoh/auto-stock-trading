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

if TYPE_CHECKING:
    from datetime import date, datetime

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.application.trading.planning import AutomationTransition
    from auto_stock_trading.domain.orders.account import AccountSnapshotObservation
    from auto_stock_trading.domain.orders.records import OrderPlanRecord, OrderRecord

_SOURCE: Final = "KIS"
_OPERATION: Final = "account_balance"
_STATE_CHANGE: Final = "state_change"
_API_FAILURE: Final = "api_failure"
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
            open_orders = await session.scalar(
                select(func.count())
                .select_from(OrderRow)
                .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
                .where(
                    OrderPlanRow.environment == environment,
                    OrderRow.state.in_(_OPEN_STATES),
                )
            )
            attempts = await session.scalar(
                select(func.count())
                .select_from(OrderRow)
                .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
                .where(
                    OrderPlanRow.environment == environment,
                    OrderPlanRow.trading_date == trading_date,
                )
            )
            buy_amount = await session.scalar(
                select(func.coalesce(func.sum(OrderRow.quantity * OrderRow.limit_price), 0))
                .select_from(OrderRow)
                .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
                .where(
                    OrderPlanRow.environment == environment,
                    OrderPlanRow.trading_date == trading_date,
                    OrderRow.side == "buy",
                    OrderRow.state.in_(_BUY_COUNTED_STATES),
                )
            )
            recent_states = (
                await session.scalars(
                    select(OrderRow.state)
                    .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
                    .where(OrderPlanRow.environment == environment)
                    .order_by(OrderRow.created_at.desc(), OrderRow.sequence.desc())
                    .limit(20)
                )
            ).all()
        consecutive = 0
        for state in recent_states:
            if state != OrderState.REJECTED.value:
                break
            consecutive += 1
        return StoredCounters(
            open_orders=open_orders or 0,
            daily_order_attempts=attempts or 0,
            daily_buy_amount=Decimal(buy_amount or 0),
            consecutive_rejects=consecutive,
            unreconciled_orders=bool(open_orders),
        )

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

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


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
                limit_value=decision.limit_value,
                projected_value=decision.projected_value,
                passed=decision.passed,
            )
        )
