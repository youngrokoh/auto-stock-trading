"""주문 정정 저장소(ADR-0011). 주문번호 갱신과 판정 기록을 한 트랜잭션에서 처리한다."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import RawApiResponseRow
from auto_stock_trading.adapters.database.trading_order_writes import (
    broker_order_query,
    next_event_sequence,
    tracked_order,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    OrderEventRow,
    OrderRow,
    RiskDecisionRow,
)
from auto_stock_trading.domain.orders.models import OrderState

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.application.trading.revision import RevisionRecord
    from auto_stock_trading.application.trading.submission import TrackedOrder
    from auto_stock_trading.domain.market_data.models import RawBrokerResponse

_SOURCE: Final = "KIS"
_API_FAILURE: Final = "api_failure"
_REVISED: Final = "order_revised"
_REVISE_FAILED: Final = "order_revise_failed"
_OPEN_STATES: Final = (OrderState.SUBMITTED.value, OrderState.PARTIALLY_FILLED.value)
_DETAIL_LIMIT: Final = 500


def _detail(record: RevisionRecord, previous_broker_order_id: str | None) -> str:
    """정정 추적에 필요한 사실만 남긴다. 원주문번호가 여기서만 보존된다."""
    acknowledgement = record.acknowledgement
    return (
        f"attempt={record.attempt} price={record.limit_price:.0f} "
        f"previous_broker_order_id={previous_broker_order_id or '-'} "
        f"broker_order_id={acknowledgement.broker_order_id or '-'} "
        f"msg_cd={acknowledgement.message_code}"
    )[:_DETAIL_LIMIT]


@final
class PostgresRevisionStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresRevisionStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresRevisionStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def open_order(
        self,
        environment: str,
        broker_order_id: str,
    ) -> TrackedOrder | None:
        statement = broker_order_query(environment, broker_order_id).where(
            OrderRow.state.in_(_OPEN_STATES)
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().first()
        if row is None:
            return None
        order_row, symbol, plan_id = row
        return tracked_order(order_row, symbol, plan_id)

    async def next_revision_attempt(self, order_id: UUID) -> int:
        """판정 회차. 계획 시점이 1회차이므로 정정은 2회차부터다."""
        statement = select(func.max(RiskDecisionRow.attempt)).where(
            RiskDecisionRow.order_id == order_id
        )
        async with self._sessions() as session:
            highest = await session.scalar(statement)
        return (highest or 1) + 1

    async def record_revision(self, record: RevisionRecord) -> None:
        """증권사 주문번호를 새 번호로 갱신한다. 상태와 수량은 바꾸지 않는다."""
        acknowledgement = record.acknowledgement
        async with self._sessions.begin() as session:
            current = await session.scalar(select(OrderRow).where(OrderRow.id == record.order_id))
            if current is None:
                message = f"unknown order {record.order_id}"
                raise LookupError(message)
            previous = current.broker_order_id
            _ = await session.execute(
                update(OrderRow)
                .where(OrderRow.id == record.order_id)
                .values(
                    broker_order_id=acknowledgement.broker_order_id,
                    broker_org_no=acknowledgement.broker_org_no or current.broker_org_no,
                    broker_order_time=(
                        acknowledgement.broker_order_time or current.broker_order_time
                    ),
                    limit_price=record.limit_price,
                    revision_count=current.revision_count + 1,
                    updated_at=record.occurred_at,
                )
            )
            await self._add_event(session, record, _REVISED, previous)
            self._add_decisions(session, record)

    async def record_revision_rejection(self, record: RevisionRecord) -> None:
        """거절은 사실로 남기고 주문은 건드리지 않는다."""
        async with self._sessions.begin() as session:
            current = await session.scalar(select(OrderRow).where(OrderRow.id == record.order_id))
            previous = None if current is None else current.broker_order_id
            await self._add_event(session, record, _REVISE_FAILED, previous)
            self._add_decisions(session, record)

    async def save_broker_response(self, raw: RawBrokerResponse) -> None:
        async with self._sessions.begin() as session:
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
                    detail=detail,
                    occurred_at=occurred_at,
                )
            )

    async def _add_event(
        self,
        session: AsyncSession,
        record: RevisionRecord,
        reason_code: str,
        previous_broker_order_id: str | None,
    ) -> None:
        state = await session.scalar(select(OrderRow.state).where(OrderRow.id == record.order_id))
        session.add(
            OrderEventRow(
                id=uuid4(),
                order_id=record.order_id,
                sequence=await next_event_sequence(session, record.order_id),
                previous_state=state,
                state=state or OrderState.SUBMITTED.value,
                reason_code=reason_code,
                detail=_detail(record, previous_broker_order_id),
                occurred_at=record.occurred_at,
            )
        )

    def _add_decisions(self, session: AsyncSession, record: RevisionRecord) -> None:
        for decision in record.decisions:
            session.add(
                RiskDecisionRow(
                    id=uuid4(),
                    order_id=record.order_id,
                    rule_code=decision.rule.value,
                    attempt=record.attempt,
                    limit_value=decision.limit_value,
                    projected_value=decision.projected_value,
                    passed=decision.passed,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
