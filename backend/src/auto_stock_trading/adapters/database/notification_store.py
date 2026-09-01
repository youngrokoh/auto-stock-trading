"""알림 아웃박스 저장소(ADR-0014 결정 2).

투영은 **anti-join**이다. 아직 아웃박스 행이 없는 이벤트를 찾으므로 시각 커서를 쓰지 않고, 따라서
커밋 순서가 뒤바뀐 이벤트도 놓치지 않는다. 중복은 `(environment, source, source_id)` 유일 제약이
막는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import ColumnElement, case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.notification_rows import (
    NotificationOutboxRow,
    NotificationWatermarkRow,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    OrderEventRow,
    OrderPlanRow,
    OrderRow,
    RiskDecisionRow,
)
from auto_stock_trading.application.notifications.dispatch import OutboxEntry
from auto_stock_trading.domain.notifications.events import (
    EventSource,
    NotificationCandidate,
)
from auto_stock_trading.domain.orders.models import OrderSide

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.orm import InstrumentedAttribute

# 재시도 상한(ADR-0014 결정 8). 상한이 없으면 도달 불가능한 알림이 매 폴마다 한도를 쓴다.
# 상한에 닿은 행은 `failed`로 남고 다음 폴의 대상이 아니지만, 사라지지 않고 실패 건수로 보인다.
_RECONCILE_PROBLEM: Final = "reconcile_problem"
_NO_CAPACITY: Final = "no_capacity"


def _no_capacity_parts(event_type: str, detail: str | None) -> tuple[str | None, str | None]:
    """자리 없음 이벤트의 상세를 종목과 규칙으로 되돌린다(ADR-0020).

    저장은 `"<종목> <규칙>"` 한 줄이지만 알림 본문은 둘을 다른 자리에 쓴다. 자유 문구가 아니라
    우리가 만든 두 값이므로 되돌려 쓸 수 있다.
    """
    if event_type != _NO_CAPACITY or not detail:
        return None, None
    symbol, _, rule = detail.partition(" ")
    return symbol or None, rule or None


MAX_DELIVERY_ATTEMPTS = 5

_BLOCKED = "blocked"
_PENDING = "pending"
_SENT = "sent"
_FAILED = "failed"


def _not_projected(
    source: EventSource,
    environment: str,
    source_id: InstrumentedAttribute[UUID],
) -> ColumnElement[bool]:
    """아직 투영되지 않은 이벤트인지. anti-join의 조건이다."""
    projected = (
        select(NotificationOutboxRow.id)
        .where(
            NotificationOutboxRow.environment == environment,
            NotificationOutboxRow.source == source.value,
            NotificationOutboxRow.source_id == source_id,
        )
        .exists()
    )
    return ~projected


@final
class PostgresNotificationOutboxStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresNotificationOutboxStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresNotificationOutboxStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def projection_watermark(self, environment: str) -> datetime | None:
        statement = select(NotificationWatermarkRow.projected_from).where(
            NotificationWatermarkRow.environment == environment
        )
        async with self._sessions() as session:
            return await session.scalar(statement)

    async def set_projection_watermark(self, environment: str, at: datetime) -> None:
        statement = (
            insert(NotificationWatermarkRow)
            .values(
                id=uuid4(),
                environment=environment,
                projected_from=at,
                created_at=at,
                updated_at=at,
            )
            .on_conflict_do_nothing(constraint="uq_notification_watermark_environment")
        )
        async with self._sessions.begin() as session:
            _ = await session.execute(statement)

    async def unprojected_events(
        self,
        environment: str,
        since: datetime,
    ) -> tuple[NotificationCandidate, ...]:
        async with self._sessions() as session:
            candidates = [
                *await self._order_events(session, environment, since),
                *await self._automation_events(session, environment, since),
                *await self._risk_decisions(session, environment, since),
            ]
        return tuple(sorted(candidates, key=lambda candidate: candidate.occurred_at))

    async def _order_events(
        self,
        session: AsyncSession,
        environment: str,
        since: datetime,
    ) -> list[NotificationCandidate]:
        statement = (
            select(OrderEventRow, OrderRow, InstrumentRow)
            .join(OrderRow, OrderRow.id == OrderEventRow.order_id)
            .join(OrderPlanRow, OrderPlanRow.id == OrderRow.plan_id)
            .join(InstrumentRow, InstrumentRow.id == OrderRow.instrument_id)
            .where(
                OrderPlanRow.environment == environment,
                OrderEventRow.occurred_at >= since,
                _not_projected(EventSource.ORDER_EVENT, environment, OrderEventRow.id),
            )
        )
        rows = (await session.execute(statement)).tuples().all()
        return [
            NotificationCandidate(
                source=EventSource.ORDER_EVENT,
                source_id=event.id,
                occurred_at=event.occurred_at,
                previous_state=event.previous_state,
                state=event.state,
                reason_code=event.reason_code,
                symbol=instrument.symbol,
                symbol_name=instrument.name,
                side=OrderSide(order.side),
                quantity=order.quantity,
                limit_price=order.limit_price,
                broker_order_id=order.broker_order_id,
                event_type=None,
                rule_code=None,
            )
            for event, order, instrument in rows
        ]

    async def _automation_events(
        self,
        session: AsyncSession,
        environment: str,
        since: datetime,
    ) -> list[NotificationCandidate]:
        statement = select(AutomationEventRow).where(
            AutomationEventRow.environment == environment,
            AutomationEventRow.occurred_at >= since,
            _not_projected(EventSource.AUTOMATION_EVENT, environment, AutomationEventRow.id),
        )
        rows = (await session.scalars(statement)).all()
        return [
            NotificationCandidate(
                source=EventSource.AUTOMATION_EVENT,
                source_id=row.id,
                occurred_at=row.occurred_at,
                previous_state=row.previous_state,
                state=row.state,
                # 상세는 사유보다 뒤에 온다. 사유가 없을 때만 상세를 쓴다.
                reason_code=row.reason_code or row.detail,
                symbol=_no_capacity_parts(row.event_type, row.detail)[0],
                symbol_name=None,
                side=None,
                quantity=None,
                limit_price=None,
                # 재조정 문제의 상세는 구조상 주문 참조다. 이걸 버리면 "어느 주문인지 없는 경고"가
                # 나가고 사람이 행동할 수 없다(2026-08-26 실측 결함). 다른 유형의 상세는 자유 문구라
                # 본문에 넣지 않는다.
                broker_order_id=row.detail if row.event_type == _RECONCILE_PROBLEM else None,
                event_type=row.event_type,
                rule_code=_no_capacity_parts(row.event_type, row.detail)[1],
            )
            for row in rows
        ]

    async def _risk_decisions(
        self,
        session: AsyncSession,
        environment: str,
        since: datetime,
    ) -> list[NotificationCandidate]:
        """차단 판정만 읽는다. 통과한 판정은 알림 대상이 아니다(결정 3-1).

        위험판정 행에는 시각이 없다. 주문 계획의 생성 시각을 이벤트 시각으로 쓴다.
        """
        statement = (
            select(RiskDecisionRow, OrderRow, InstrumentRow, OrderPlanRow)
            .join(OrderRow, OrderRow.id == RiskDecisionRow.order_id)
            .join(OrderPlanRow, OrderPlanRow.id == OrderRow.plan_id)
            .join(InstrumentRow, InstrumentRow.id == OrderRow.instrument_id)
            .where(
                OrderPlanRow.environment == environment,
                OrderPlanRow.created_at >= since,
                RiskDecisionRow.passed.is_(False),
                _not_projected(EventSource.RISK_DECISION, environment, RiskDecisionRow.id),
            )
        )
        rows = (await session.execute(statement)).tuples().all()
        return [
            NotificationCandidate(
                source=EventSource.RISK_DECISION,
                source_id=decision.id,
                occurred_at=plan.created_at,
                previous_state=None,
                state=_BLOCKED,
                reason_code=None,
                symbol=instrument.symbol,
                symbol_name=instrument.name,
                side=OrderSide(order.side),
                quantity=order.quantity,
                limit_price=order.limit_price,
                broker_order_id=None,
                event_type=None,
                rule_code=decision.rule_code,
            )
            for decision, order, instrument, plan in rows
        ]

    async def save_outbox(self, entries: tuple[OutboxEntry, ...]) -> int:
        if not entries:
            return 0
        values = [
            {
                "id": entry.entry_id,
                "environment": entry.environment,
                "source": entry.source,
                "source_id": entry.source_id,
                "kind": entry.kind,
                "severity": entry.severity,
                "body": entry.body,
                "state": entry.state,
                "attempts": 0,
                "last_error": entry.last_error,
                "event_occurred_at": entry.event_occurred_at,
                "created_at": entry.event_occurred_at,
                "sent_at": None,
            }
            for entry in entries
        ]
        statement = (
            insert(NotificationOutboxRow)
            .values(values)
            .on_conflict_do_nothing(constraint="uq_notification_outbox_event")
            .returning(NotificationOutboxRow.id)
        )
        async with self._sessions.begin() as session:
            saved = (await session.scalars(statement)).all()
        return len(saved)

    async def pending_entries(self, environment: str, limit: int) -> tuple[OutboxEntry, ...]:
        statement = (
            select(NotificationOutboxRow)
            .where(
                NotificationOutboxRow.environment == environment,
                NotificationOutboxRow.state == _PENDING,
            )
            .order_by(NotificationOutboxRow.event_occurred_at)
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            OutboxEntry(
                entry_id=row.id,
                environment=row.environment,
                source=row.source,
                source_id=row.source_id,
                kind=row.kind,
                severity=row.severity,
                body=row.body,
                state=row.state,
                last_error=row.last_error,
                event_occurred_at=row.event_occurred_at,
            )
            for row in rows
        )

    async def mark_sent(self, entry_id: UUID, at: datetime, note: str | None) -> None:
        statement = (
            update(NotificationOutboxRow)
            .where(NotificationOutboxRow.id == entry_id)
            .values(
                state=_SENT,
                sent_at=at,
                attempts=NotificationOutboxRow.attempts + 1,
                last_error=note,
            )
        )
        async with self._sessions.begin() as session:
            _ = await session.execute(statement)

    async def mark_failed(self, entry_id: UUID, error: str, at: datetime) -> None:
        """실패는 사실로 남는다. 상한 전까지는 `pending`을 유지해 다음 폴이 다시 시도한다.

        상태 판정을 같은 `UPDATE` 안에서 한다 — 읽고 나서 쓰면 두 폴이 겹칠 때 시도 횟수가 어긋난다.
        """
        _ = at
        attempts = NotificationOutboxRow.attempts + 1
        statement = (
            update(NotificationOutboxRow)
            .where(NotificationOutboxRow.id == entry_id)
            .values(
                attempts=attempts,
                last_error=error[:500],
                sent_at=None,
                state=case(
                    (attempts >= MAX_DELIVERY_ATTEMPTS, _FAILED),
                    else_=_PENDING,
                ),
            )
        )
        async with self._sessions.begin() as session:
            _ = await session.execute(statement)

    async def counts(self, environment: str) -> tuple[int, int, int, datetime | None]:
        """미발신·실패·당일 발신 건수와 가장 오래된 미발신 이벤트 시각."""
        pending = select(func.count()).where(
            NotificationOutboxRow.environment == environment,
            NotificationOutboxRow.state == _PENDING,
        )
        failed = select(func.count()).where(
            NotificationOutboxRow.environment == environment,
            NotificationOutboxRow.state == _FAILED,
        )
        sent = select(func.count()).where(
            NotificationOutboxRow.environment == environment,
            NotificationOutboxRow.state == _SENT,
        )
        oldest = select(func.min(NotificationOutboxRow.event_occurred_at)).where(
            NotificationOutboxRow.environment == environment,
            NotificationOutboxRow.state == _PENDING,
        )
        async with self._sessions() as session:
            return (
                await session.scalar(pending) or 0,
                await session.scalar(failed) or 0,
                await session.scalar(sent) or 0,
                await session.scalar(oldest),
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
