"""실시간 체결통보 저장소. 통보 저장과 주문 상태 전이를 한 트랜잭션에서 처리한다."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.trading_order_writes import (
    OrderTransition,
    broker_order_query,
    tracked_order,
    transition_order,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    FillNotificationRow,
    NotificationSessionRow,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.application.trading.submission import TrackedOrder
    from auto_stock_trading.domain.orders.records import FillNotificationRecord

_LISTENER_STATE: Final = "listener_state"
_FILL_NOTIFICATION: Final = "FILL_NOTIFICATION"
_CONNECTED: Final = "connected"
_CLOSED: Final = "closed"
_DISCONNECTED: Final = "disconnected"
# 실시간 체결통보 계약의 부착 판정 허용 지연.
ATTACH_MAX_AGE_SECONDS: Final = 30
HEARTBEAT_SECONDS: Final = 10


@final
class PostgresNotificationStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
        max_age_seconds: int = ATTACH_MAX_AGE_SECONDS,
    ) -> None:
        self._engine = engine
        self._sessions = sessions
        self._max_age = timedelta(seconds=max_age_seconds)

    @classmethod
    def from_url(cls, database_url: str) -> PostgresNotificationStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresNotificationStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def order_by_broker_order_id(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None:
        statement = broker_order_query(environment, broker_order_id)
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().first()
        if row is None:
            return None
        order_row, symbol, plan_id = row
        return tracked_order(order_row, symbol, plan_id)

    async def record_notification(self, record: FillNotificationRecord) -> None:
        """통보 한 건과 상태 전이를 같은 트랜잭션에 넣는다. 같은 프레임을 두 번 반영하지 않는다."""
        notification = record.notification
        async with self._sessions.begin() as session:
            session.add(
                FillNotificationRow(
                    id=uuid4(),
                    environment=record.environment,
                    account_reference=record.account_reference,
                    order_id=record.order_id,
                    broker_order_id=notification.broker_order_id,
                    original_broker_order_id=notification.original_broker_order_id or None,
                    notification_kind=notification.kind.value,
                    side=notification.side.value,
                    symbol=notification.symbol,
                    quantity=notification.quantity,
                    price=notification.price,
                    order_quantity=notification.order_quantity,
                    broker_event_time=notification.broker_event_time,
                    rejected=notification.rejected,
                    revise_code=notification.revise_code,
                    accept_code=notification.accept_code,
                    branch_no=notification.branch_no,
                    masked_payload=record.masked_payload,
                    problem=None if record.problem is None else record.problem.value,
                    received_at=record.received_at,
                    created_at=record.received_at,
                )
            )
            if record.order_id is None or record.state is None:
                return
            values: dict[str, object] = {}
            if record.filled_quantity is not None:
                values["filled_quantity"] = record.filled_quantity
            if record.average_fill_price is not None:
                values["average_fill_price"] = record.average_fill_price
            await transition_order(
                session,
                OrderTransition(
                    order_id=record.order_id,
                    state=record.state,
                    reason_code=_FILL_NOTIFICATION,
                    occurred_at=record.received_at,
                    values=values,
                ),
            )

    async def start_session(self, environment: str, transaction_id: str, at: datetime) -> UUID:
        """세션을 연다. 같은 환경에 연결된 세션이 둘이면 부분 유일 인덱스가 거부한다."""
        session_id = uuid4()
        async with self._sessions.begin() as session:
            session.add(
                NotificationSessionRow(
                    id=session_id,
                    environment=environment,
                    transaction_id=transaction_id,
                    state=_CONNECTED,
                    started_at=at,
                    last_heartbeat_at=at,
                    ended_at=None,
                    disconnect_reason=None,
                )
            )
        return session_id

    async def close_open_sessions(self, environment: str, reason: str, at: datetime) -> int:
        """남아 있는 연결 세션을 종료 처리한다. 리스너 시작 시 중복 반영을 막는다."""
        async with self._sessions.begin() as session:
            open_sessions = (
                await session.scalars(
                    select(NotificationSessionRow.id).where(
                        NotificationSessionRow.environment == environment,
                        NotificationSessionRow.state == _CONNECTED,
                    )
                )
            ).all()
            if open_sessions:
                _ = await session.execute(
                    update(NotificationSessionRow)
                    .where(NotificationSessionRow.id.in_(open_sessions))
                    .values(state=_CLOSED, ended_at=at, disconnect_reason=reason)
                )
        return len(open_sessions)

    async def heartbeat(self, session_id: UUID, at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                update(NotificationSessionRow)
                .where(NotificationSessionRow.id == session_id)
                .values(last_heartbeat_at=at)
            )

    async def end_session(self, session_id: UUID, reason: str, at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                update(NotificationSessionRow)
                .where(NotificationSessionRow.id == session_id)
                .values(state=_DISCONNECTED, ended_at=at, disconnect_reason=reason)
            )

    async def attached(self, environment: str, now: datetime) -> bool:
        """제출 게이트의 판정. 연결 상태이고 심박이 허용 지연 안이어야 부착이다."""
        statement = select(NotificationSessionRow.id).where(
            NotificationSessionRow.environment == environment,
            NotificationSessionRow.state == _CONNECTED,
            NotificationSessionRow.last_heartbeat_at >= now - self._max_age,
        )
        async with self._sessions() as session:
            return await session.scalar(statement) is not None

    async def record_listener_event(
        self,
        environment: str,
        reason_code: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=environment,
                    event_type=_LISTENER_STATE,
                    previous_state=None,
                    state=None,
                    reason_code=reason_code,
                    detail=detail,
                    occurred_at=occurred_at,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
