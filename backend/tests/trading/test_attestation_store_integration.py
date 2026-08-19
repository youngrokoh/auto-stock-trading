from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.brokers.kis_orders import BrokerAcknowledgement
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_attestation_store import (
    PostgresAttestationStore,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    AutomationStateRow,
    FillNotificationRow,
    NotificationSessionRow,
    OrderEventRow,
    OrderPlanRow,
    OrderRow,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.attestation import (
    AttestationInput,
    OrderAttestor,
)
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderSide,
    OrderState,
    OrderType,
)
from auto_stock_trading.domain.orders.records import OrderPlanRecord, OrderRecord
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    type AttestationScenario = Callable[
        [PostgresAttestationStore, PostgresTradingStore, AsyncConnection],
        Awaitable[None],
    ]

_NOW: Final = datetime(2026, 8, 19, 7, 30, tzinfo=UTC)
_SUBMITTED_AT: Final = datetime(2026, 8, 19, 0, 6, tzinfo=UTC)
_SESSION_START: Final = datetime(2026, 8, 19, 2, 42, tzinfo=UTC)
_TRADING_DATE: Final = date(2026, 8, 19)
_ENVIRONMENT: Final = "paper"
_SYMBOL: Final = "990004"
_BROKER_ORDER_ID: Final = "0000099001"
_OPERATOR: Final = "yroh1"
_EVIDENCE: Final = "KIS 모의투자 잔고화면 2026-08-19 16:10"


def _order_record() -> OrderRecord:
    return OrderRecord(
        client_order_id=uuid4().hex[:32],
        sequence=1,
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=2,
        limit_price=Decimal(250000),
        reference_price=Decimal(249750),
        reference_source="KIS",
        reference_received_at=_SUBMITTED_AT,
        state=OrderState.PLANNED,
        reject_code=None,
        decisions=(),
    )


def _plan(order: OrderRecord) -> OrderPlanRecord:
    return OrderPlanRecord(
        plan_id=uuid4(),
        environment=_ENVIRONMENT,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"short_period":5}',
        signal_date=_TRADING_DATE,
        trading_date=_TRADING_DATE,
        account_snapshot_id=None,
        nav_basis=Decimal(10_000_000),
        session_open_nav=Decimal(10_000_000),
        automation_state=AutomationState.RUNNING,
        status="created",
        block_code=None,
        planned_at=_SUBMITTED_AT,
        orders=(order,),
    )


def _acknowledgement() -> BrokerAcknowledgement:
    return BrokerAcknowledgement(
        accepted=True,
        broker_order_id=_BROKER_ORDER_ID,
        broker_org_no="00950",
        broker_order_time="090612",
        message_code="40600000",
        message="주문 전송 완료 되었습니다.",
        raw=RawBrokerResponse(
            operation=BrokerOperation.ORDER_SUBMIT,
            endpoint="/uapi/domestic-stock/v1/trading/order-cash",
            request_fingerprint=f"order_submit:abcdef123456:{_SYMBOL}:buy:1",
            received_at=_SUBMITTED_AT,
            payload_json='{"rt_cd":"0"}',
        ),
    )


async def _submitted_order(
    store: PostgresTradingStore,
    connection: AsyncConnection,
) -> tuple[UUID, str]:
    _ = await _ensure_instrument(connection, _SYMBOL)
    record = _order_record()
    plan = _plan(record)
    await store.save_plan(plan)
    orders = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, plan.plan_id)
    await store.record_submission(orders[0].order_id, _acknowledgement(), _SUBMITTED_AT)
    return orders[0].order_id, record.client_order_id


async def _listener_session(connection: AsyncConnection, started_at: datetime) -> None:
    _ = await connection.execute(
        insert(NotificationSessionRow).values(
            id=uuid4(),
            environment=_ENVIRONMENT,
            transaction_id="H0STCNI9",
            state="disconnected",
            started_at=started_at,
            last_heartbeat_at=started_at,
            ended_at=started_at + timedelta(minutes=1),
            disconnect_reason="STOPPED",
        )
    )


def _request(**overrides: object) -> AttestationInput:
    values: dict[str, object] = {
        "environment": _ENVIRONMENT,
        "broker_order_id": _BROKER_ORDER_ID,
        "state": OrderState.FILLED,
        "filled_quantity": 2,
        "average_fill_price": Decimal(248750),
        "operator": _OPERATOR,
        "evidence": _EVIDENCE,
    }
    values.update(overrides)
    return AttestationInput(**values)  # pyright: ignore[reportArgumentType]


def test_a_pre_listener_order_is_attested_with_an_audit_trail() -> None:
    async def scenario(
        attestations: PostgresAttestationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        order_id, client_order_id = await _submitted_order(store, connection)
        await _listener_session(connection, _SESSION_START)

        result = await OrderAttestor(store=attestations).attest(_request(), _NOW)

        assert result.applied
        assert result.client_order_id == client_order_id
        state, filled, price = (
            (
                await connection.execute(
                    select(
                        OrderRow.state,
                        OrderRow.filled_quantity,
                        OrderRow.average_fill_price,
                    ).where(OrderRow.id == order_id)
                )
            )
            .tuples()
            .one()
        )
        assert state == OrderState.FILLED.value
        assert filled == 2
        assert price == Decimal(248750)
        reason, detail = (
            (
                await connection.execute(
                    select(OrderEventRow.reason_code, OrderEventRow.detail)
                    .where(OrderEventRow.order_id == order_id)
                    .order_by(OrderEventRow.sequence.desc())
                    .limit(1)
                )
            )
            .tuples()
            .one()
        )
        assert reason == "HUMAN_ATTESTED"
        assert detail is not None
        assert _OPERATOR in detail
        assert _EVIDENCE in detail
        event_type, event_reason = (
            (
                await connection.execute(
                    select(AutomationEventRow.event_type, AutomationEventRow.reason_code).where(
                        AutomationEventRow.environment == _ENVIRONMENT
                    )
                )
            )
            .tuples()
            .one()
        )
        assert event_type == "attestation"
        assert event_reason == "HUMAN_ATTESTED"

    anyio.run(_run_scenario, scenario)


def test_an_order_submitted_after_the_first_session_is_refused() -> None:
    async def scenario(
        attestations: PostgresAttestationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        order_id, _ = await _submitted_order(store, connection)
        await _listener_session(connection, _SUBMITTED_AT - timedelta(minutes=1))

        result = await OrderAttestor(store=attestations).attest(_request(), _NOW)

        assert not result.applied
        assert result.reason == "LISTENER_COVERED"
        state = await connection.scalar(select(OrderRow.state).where(OrderRow.id == order_id))
        assert state == OrderState.SUBMITTED.value

    anyio.run(_run_scenario, scenario)


def test_without_listener_history_the_path_is_closed() -> None:
    async def scenario(
        attestations: PostgresAttestationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = await _submitted_order(store, connection)

        result = await OrderAttestor(store=attestations).attest(_request(), _NOW)

        assert not result.applied
        assert result.reason == "NO_LISTENER_HISTORY"

    anyio.run(_run_scenario, scenario)


def test_a_cancellation_without_fills_leaves_the_price_empty() -> None:
    async def scenario(
        attestations: PostgresAttestationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        order_id, _ = await _submitted_order(store, connection)
        await _listener_session(connection, _SESSION_START)

        result = await OrderAttestor(store=attestations).attest(
            _request(
                state=OrderState.CANCELED,
                filled_quantity=0,
                average_fill_price=None,
            ),
            _NOW,
        )

        assert result.applied
        state, filled, price = (
            (
                await connection.execute(
                    select(
                        OrderRow.state,
                        OrderRow.filled_quantity,
                        OrderRow.average_fill_price,
                    ).where(OrderRow.id == order_id)
                )
            )
            .tuples()
            .one()
        )
        assert state == OrderState.CANCELED.value
        assert filled == 0
        assert price is None

    anyio.run(_run_scenario, scenario)


def test_attesting_twice_is_refused_because_the_order_is_no_longer_open() -> None:
    async def scenario(
        attestations: PostgresAttestationStore,
        store: PostgresTradingStore,
        connection: AsyncConnection,
    ) -> None:
        _ = await _submitted_order(store, connection)
        await _listener_session(connection, _SESSION_START)
        attestor = OrderAttestor(store=attestations)

        first = await attestor.attest(_request(), _NOW)
        second = await attestor.attest(_request(), _NOW)

        assert first.applied
        assert not second.applied
        assert second.reason == "NOT_OPEN"

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: AttestationScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await _purge_environment(connection)
        attestations = PostgresAttestationStore.from_connection(connection)
        store = PostgresTradingStore.from_connection(connection)
        try:
            await scenario(attestations, store, connection)
        finally:
            await attestations.close()
            await store.close()
            await transaction.rollback()
    await engine.dispose()


async def _purge_environment(connection: AsyncConnection) -> None:
    """이 트랜잭션 안에서만 환경 데이터를 비운다. 실제 실행 기록은 롤백으로 복원된다."""
    for table in (
        FillNotificationRow,
        NotificationSessionRow,
        OrderPlanRow,
        AutomationEventRow,
        AutomationStateRow,
    ):
        _ = await connection.execute(delete(table).where(table.environment == _ENVIRONMENT))


async def _ensure_instrument(connection: AsyncConnection, symbol: str) -> UUID:
    existing = await connection.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == symbol).limit(1)
    )
    if existing is not None:
        return existing
    instrument_id = uuid4()
    _ = await connection.execute(
        insert(InstrumentRow).values(
            id=instrument_id,
            country="KR",
            exchange="KRX",
            symbol=symbol,
            product_type="stock",
            currency="KRW",
            name="대조 종결 통합 테스트 종목",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="active",
            source="TEST",
            source_as_of=_TRADING_DATE,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return instrument_id
