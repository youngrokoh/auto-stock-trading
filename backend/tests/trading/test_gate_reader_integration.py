"""게이트 판정이 읽는 측정값(모의투자·실전투자 전환 게이트 §3).

정책은 "내부 주문·체결·잔고와 증권사 상태의 **미조정 건이 0건**"이라고 쓴다. 발생 이력이 아니라 지금
미조정 상태인 건수다. 해소 여부 없이 전부 세면 **한 번 문제가 생긴 뒤에는 이 조건이 다시 충족될 수
없고**, 정책이 요구하지 않은 영구 차단이 된다.

참조한 주문이 종결됐다면 그 발산은 닫혔다. 그것이 파생으로 알 수 있는 해소다.
"""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.gate_reader import PostgresGateReader
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_reconcile_store import PostgresReconcileStore
from auto_stock_trading.adapters.database.trading_rows import (
    AutomationEventRow,
    AutomationStateRow,
    OrderPlanRow,
    OrderRow,
    ReconcileResolutionRow,
)
from auto_stock_trading.domain.orders.fills import ReconcileProblem
from auto_stock_trading.domain.orders.models import OrderSide, OrderState, OrderType
from auto_stock_trading.domain.orders.reconciliation import (
    ResolutionReason,
    ResolutionRejection,
    ResolutionRequest,
    resolve_problems,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    type GateScenario = Callable[[PostgresGateReader, AsyncConnection], Awaitable[None]]

_NOW: Final = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
_TRADING_DATE: Final = date(2026, 8, 18)
_ENVIRONMENT: Final = "paper"
_SYMBOL: Final = "990004"
_BROKER_ORDER_ID: Final = "0000112233"


async def _run_scenario(scenario: GateScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        for table in (
            OrderPlanRow,
            AutomationEventRow,
            AutomationStateRow,
            ReconcileResolutionRow,
        ):
            _ = await connection.execute(delete(table).where(table.environment == _ENVIRONMENT))
        reader = PostgresGateReader.from_connection(connection)
        try:
            await scenario(reader, connection)
        finally:
            await reader.close()
            await transaction.rollback()
    await engine.dispose()


async def _instrument(connection: AsyncConnection) -> UUID:
    existing = await connection.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == _SYMBOL).limit(1)
    )
    if existing is not None:
        return existing
    instrument_id = uuid4()
    _ = await connection.execute(
        insert(InstrumentRow).values(
            id=instrument_id,
            country="KR",
            exchange="KRX",
            symbol=_SYMBOL,
            product_type="stock",
            currency="KRW",
            name="게이트 통합 테스트 종목",
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


async def _order(
    connection: AsyncConnection,
    state: OrderState,
    *,
    trading_date: date = _TRADING_DATE,
    broker_order_id: str = _BROKER_ORDER_ID,
) -> None:
    plan_id = uuid4()
    _ = await connection.execute(
        insert(OrderPlanRow).values(
            id=plan_id,
            environment=_ENVIRONMENT,
            trading_date=trading_date,
            strategy_name="test",
            strategy_version="1",
            parameters_json="{}",
            signal_date=trading_date,
            automation_state="running",
            status="created",
            planned_at=_NOW,
            created_at=_NOW,
        )
    )
    _ = await connection.execute(
        insert(OrderRow).values(
            id=uuid4(),
            plan_id=plan_id,
            sequence=0,
            instrument_id=await _instrument(connection),
            client_order_id=uuid4().hex[:32],
            side=OrderSide.BUY.value,
            order_type=OrderType.LIMIT.value,
            quantity=1,
            filled_quantity=0,
            limit_price=1000,
            reference_price=1000,
            reference_source="quote",
            reference_received_at=_NOW,
            state=state.value,
            broker_order_id=broker_order_id,
            broker_org_no="00950",
            submitted_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )


async def _resolution(connection: AsyncConnection, broker_order_id: str) -> None:
    _ = await connection.execute(
        insert(ReconcileResolutionRow).values(
            id=uuid4(),
            environment=_ENVIRONMENT,
            broker_order_id=broker_order_id,
            operator="사람",
            evidence="시스템 밖에서 낸 수동 주문",
            problem_count=1,
            resolved_at=_NOW,
        )
    )


async def _problem(connection: AsyncConnection, detail: str) -> None:
    _ = await connection.execute(
        insert(AutomationEventRow).values(
            id=uuid4(),
            environment=_ENVIRONMENT,
            event_type="reconcile_problem",
            previous_state=None,
            state=None,
            reason_code=ReconcileProblem.NOTIFICATION_GAP.value,
            detail=detail,
            occurred_at=_NOW,
        )
    )


def test_a_problem_whose_order_is_settled_no_longer_counts() -> None:
    """참조 주문이 종결되면 발산이 닫혔다. 이력이 영구히 게이트를 막지 않는다."""

    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _order(connection, OrderState.FILLED)
        await _problem(connection, _BROKER_ORDER_ID)

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 0

    anyio.run(_run_scenario, scenario)


def test_expiry_settles_a_problem_the_same_way_a_cancel_does() -> None:
    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _order(connection, OrderState.EXPIRED)
        await _problem(connection, _BROKER_ORDER_ID)

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 0

    anyio.run(_run_scenario, scenario)


def test_a_problem_on_a_still_open_order_counts() -> None:
    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _order(connection, OrderState.SUBMITTED)
        await _problem(connection, _BROKER_ORDER_ID)

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 1

    anyio.run(_run_scenario, scenario)


def test_a_problem_referencing_no_order_of_ours_counts() -> None:
    """증권사만 아는 주문은 지금도 미조정이다. 확인할 수 없으면 해소로 보지 않는다."""

    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _problem(connection, "0000999999")

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 1

    anyio.run(_run_scenario, scenario)


def test_stale_open_orders_are_counted_separately_from_problems() -> None:
    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _order(connection, OrderState.SUBMITTED, trading_date=date(2026, 8, 17))

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.stale_open_orders == 1
        assert measurements.unreconciled_events == 0

    anyio.run(_run_scenario, scenario)


def test_a_resolved_broker_order_no_longer_counts() -> None:
    """사람이 설명한 발산은 미조정이 아니다(ADR-0018 결정 7)."""

    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _problem(connection, "0000999999")
        await _resolution(connection, "0000999999")

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 0

    anyio.run(_run_scenario, scenario)


def test_one_resolution_covers_repeated_observations_of_the_same_number() -> None:
    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _problem(connection, "0000999999")
        await _problem(connection, "0000999999")
        await _resolution(connection, "0000999999")

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 0

    anyio.run(_run_scenario, scenario)


def test_a_resolution_for_another_number_does_not_clear_this_one() -> None:
    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _problem(connection, "0000999999")
        await _resolution(connection, "0000888888")

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)

        assert measurements.unreconciled_events == 1

    anyio.run(_run_scenario, scenario)


def test_the_store_reads_the_facts_the_decision_needs() -> None:
    """판정에 필요한 사실만 읽는다 — 문제 건수, 우리 기록의 주문 상태, 이미 해소했는지."""

    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        _ = reader
        await _problem(connection, "0000999999")
        await _problem(connection, "0000999999")
        store = PostgresReconcileStore.from_connection(connection)
        try:
            target = await store.target(_ENVIRONMENT, "0000999999")
        finally:
            await store.close()

        assert target.problem_count == 2
        assert target.order_state is None
        assert target.resolved is False

    anyio.run(_run_scenario, scenario)


def test_saving_a_resolution_writes_the_fact_and_an_audit_event() -> None:
    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        await _problem(connection, "0000999999")
        store = PostgresReconcileStore.from_connection(connection)
        try:
            outcome = resolve_problems(
                await store.target(_ENVIRONMENT, "0000999999"),
                ResolutionRequest(
                    broker_order_id="0000999999",
                    operator="youngrokoh",
                    evidence="시스템 밖에서 낸 수동 주문",
                ),
            )
            assert not isinstance(outcome, ResolutionRejection)
            await store.save(_ENVIRONMENT, outcome, _NOW)
        finally:
            await store.close()

        measurements = await reader.measurements(_ENVIRONMENT, _TRADING_DATE)
        assert measurements.unreconciled_events == 0
        event = await connection.scalar(
            select(AutomationEventRow.detail).where(
                AutomationEventRow.event_type == "reconcile_resolved"
            )
        )
        assert event == "operator=youngrokoh evidence=시스템 밖에서 낸 수동 주문"

    anyio.run(_run_scenario, scenario)


def test_the_same_number_cannot_be_resolved_twice() -> None:
    """유일 제약이 중복 해소를 DB에서 막는다. 읽기 시점 검사에만 기대지 않는다."""

    async def scenario(reader: PostgresGateReader, connection: AsyncConnection) -> None:
        _ = reader
        await _problem(connection, "0000999999")
        await _resolution(connection, "0000999999")
        store = PostgresReconcileStore.from_connection(connection)
        try:
            target = await store.target(_ENVIRONMENT, "0000999999")
        finally:
            await store.close()

        assert target.resolved is True
        outcome = resolve_problems(
            target,
            ResolutionRequest(
                broker_order_id="0000999999",
                operator="youngrokoh",
                evidence="두 번째 시도",
            ),
        )
        assert isinstance(outcome, ResolutionRejection)
        assert outcome.reason is ResolutionReason.ALREADY_RESOLVED

    anyio.run(_run_scenario, scenario)
