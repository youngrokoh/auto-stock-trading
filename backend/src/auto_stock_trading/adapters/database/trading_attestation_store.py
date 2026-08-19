"""사람이 확인한 대조 종결 저장소(ADR-0010). 적용 범위 판정과 전이를 한 트랜잭션에서 처리한다."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.trading_order_writes import (
    OrderTransition,
    broker_order_query,
    transition_order,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    NotificationSessionRow,
)
from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.domain.orders.records import AttestationTarget

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.domain.orders.attestation import AttestationOutcome

_ATTESTATION: Final = "attestation"
_REASON: Final = "HUMAN_ATTESTED"
_DETAIL_LIMIT: Final = 500


def _detail(outcome: AttestationOutcome) -> str:
    """실행자와 근거를 함께 남긴다. 열 길이를 넘으면 잘라 저장한다."""
    return f"operator={outcome.operator} evidence={outcome.evidence}"[:_DETAIL_LIMIT]


@final
class PostgresAttestationStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresAttestationStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresAttestationStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def target(
        self,
        environment: str,
        broker_order_id: str,
    ) -> AttestationTarget | None:
        statement = broker_order_query(environment, broker_order_id)
        async with self._sessions() as session:
            row = (await session.execute(statement)).tuples().first()
        if row is None:
            return None
        order_row, symbol, _ = row
        return AttestationTarget(
            order_id=order_row.id,
            client_order_id=order_row.client_order_id,
            symbol=symbol,
            quantity=order_row.quantity,
            filled_quantity=order_row.filled_quantity,
            average_fill_price=order_row.average_fill_price,
            state=OrderState(order_row.state),
            submitted_at=order_row.submitted_at,
        )

    async def earliest_session_start(self, environment: str) -> datetime | None:
        """가장 이른 체결통보 세션 시작. 이 시각 이후 제출 주문은 이 경로를 쓸 수 없다."""
        statement = select(func.min(NotificationSessionRow.started_at)).where(
            NotificationSessionRow.environment == environment
        )
        async with self._sessions() as session:
            return await session.scalar(statement)

    async def apply_attestation(
        self,
        environment: str,
        order_id: UUID,
        outcome: AttestationOutcome,
    ) -> None:
        """상태 전이와 감사 기록을 같은 트랜잭션에 넣는다. 증권사 호출은 없다."""
        values: dict[str, object] = {"filled_quantity": outcome.filled_quantity}
        if outcome.average_fill_price is not None:
            values["average_fill_price"] = outcome.average_fill_price
        async with self._sessions.begin() as session:
            await transition_order(
                session,
                OrderTransition(
                    order_id=order_id,
                    state=outcome.state,
                    reason_code=_REASON,
                    occurred_at=outcome.occurred_at,
                    values=values,
                    detail=_detail(outcome),
                ),
            )
            session.add(
                AutomationEventRow(
                    id=uuid4(),
                    environment=environment,
                    event_type=_ATTESTATION,
                    previous_state=None,
                    state=None,
                    reason_code=_REASON,
                    detail=_detail(outcome),
                    occurred_at=outcome.occurred_at,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
