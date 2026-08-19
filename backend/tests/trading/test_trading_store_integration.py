from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.brokers.kis_orders import BrokerAcknowledgement
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_reader import PostgresTradingReader
from auto_stock_trading.adapters.database.trading_rows import (
    AccountSnapshotRow,
    AutomationEventRow,
    AutomationStateRow,
    OrderPlanRow,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.planning import AutomationTransition
from auto_stock_trading.domain.market_data.models import BrokerOperation, RawBrokerResponse
from auto_stock_trading.domain.orders.account import (
    AccountPosition,
    AccountSnapshot,
    AccountSnapshotObservation,
)
from auto_stock_trading.domain.orders.fills import ReconcileProblem
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    InvalidTransitionError,
    OrderSide,
    OrderState,
    OrderType,
)
from auto_stock_trading.domain.orders.records import OrderPlanRecord, OrderRecord
from auto_stock_trading.domain.risk.engine import PendingExposure, RiskDecision
from auto_stock_trading.domain.risk.limits import RiskRule
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

    type StoreScenario = Callable[
        [PostgresTradingStore, PostgresTradingReader, AsyncConnection],
        Awaitable[None],
    ]

_NOW: Final = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
_TRADING_DATE: Final = date(2026, 8, 18)
_ENVIRONMENT: Final = "paper"
_SYMBOL: Final = "990002"
_PRICE: Final = Decimal(100_000)


def _plan(*, status: str = "created", orders: tuple[OrderRecord, ...] = ()) -> OrderPlanRecord:
    return OrderPlanRecord(
        plan_id=uuid4(),
        environment=_ENVIRONMENT,
        strategy_name="ma-rsi",
        strategy_version="1",
        parameters_json='{"short_period":5}',
        signal_date=_TRADING_DATE,
        trading_date=_TRADING_DATE,
        account_snapshot_id=None,
        nav_basis=Decimal(100_000_000),
        session_open_nav=Decimal(100_000_000),
        automation_state=AutomationState.RUNNING,
        status=status,
        block_code=None if status == "created" else "MARKET_CLOSED",
        planned_at=_NOW,
        orders=orders,
    )


def _order(
    *,
    sequence: int = 1,
    client_order_id: str = "a" * 32,
    quantity: int = 50,
    state: OrderState = OrderState.PLANNED,
    reject_code: str | None = None,
) -> OrderRecord:
    return OrderRecord(
        client_order_id=client_order_id,
        sequence=sequence,
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=_PRICE,
        reference_price=_PRICE,
        reference_source="KIS",
        reference_received_at=_NOW,
        state=state,
        reject_code=reject_code,
        decisions=(
            RiskDecision(
                rule=RiskRule.SYMBOL_EXPOSURE,
                limit_value=Decimal(10_000_000),
                projected_value=Decimal(5_000_000),
                passed=True,
            ),
            RiskDecision(
                rule=RiskRule.ORDER_AMOUNT,
                limit_value=Decimal(5_000_000),
                projected_value=Decimal(5_000_000),
                passed=True,
            ),
        ),
    )


def _acknowledgement(*, accepted: bool = True) -> BrokerAcknowledgement:
    return BrokerAcknowledgement(
        accepted=accepted,
        broker_order_id="0000117057" if accepted else None,
        broker_org_no="00950" if accepted else None,
        broker_order_time="101153" if accepted else None,
        message_code="APBK0013" if accepted else "APBK0919",
        message="주문 전송 완료 되었습니다." if accepted else "주문가능금액이 부족합니다.",
        raw=RawBrokerResponse(
            operation=BrokerOperation.ORDER_SUBMIT,
            endpoint="/uapi/domestic-stock/v1/trading/order-cash",
            request_fingerprint="order_submit:abc123def456:990002:buy:1",
            received_at=_NOW,
            payload_json='{"rt_cd":"0"}',
        ),
    )


def _snapshot_observation(*, nav: Decimal, held: int = 0) -> AccountSnapshotObservation:
    position_value = _PRICE * held
    positions = (
        ()
        if held == 0
        else (
            AccountPosition(
                symbol=_SYMBOL,
                quantity=held,
                orderable_quantity=held,
                average_price=_PRICE,
                current_price=_PRICE,
                evaluation_amount=position_value,
                profit_loss=Decimal(0),
            ),
        )
    )
    snapshot = AccountSnapshot(
        source="KIS",
        environment=_ENVIRONMENT,
        account_reference="abc123def456",
        currency="KRW",
        cash_balance=nav - position_value,
        orderable_cash=nav - position_value,
        position_value=position_value,
        nav=nav,
        broker_net_asset=nav,
        trading_date=_TRADING_DATE,
        as_of=_NOW,
        received_at=_NOW,
        positions=positions,
    )
    return AccountSnapshotObservation(
        snapshot=snapshot,
        raw=RawBrokerResponse(
            operation=BrokerOperation.ACCOUNT_BALANCE,
            endpoint="/uapi/domestic-stock/v1/trading/inquire-balance",
            request_fingerprint="account_balance:abc123def456",
            received_at=_NOW,
            payload_json='{"rt_cd":"0"}',
        ),
    )


def test_plan_round_trips_with_orders_and_risk_decisions() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        plan = _plan(orders=(_order(), _order(sequence=2, client_order_id="b" * 32)))

        await store.save_plan(plan)

        loaded = await reader.order_plan(plan.plan_id)
        assert loaded is not None
        assert loaded.status == "created"
        assert loaded.automation_state is AutomationState.RUNNING
        assert [order.client_order_id for order in loaded.orders] == ["a" * 32, "b" * 32]
        assert [order.quantity for order in loaded.orders] == [50, 50]
        assert loaded.orders[0].symbol == _SYMBOL
        assert loaded.orders[0].reference_source == "KIS"
        assert {decision.rule for decision in loaded.orders[0].decisions} == {
            RiskRule.SYMBOL_EXPOSURE,
            RiskRule.ORDER_AMOUNT,
        }

        (summary,) = await reader.order_plans(_ENVIRONMENT, 10)
        assert summary.plan.plan_id == plan.plan_id
        assert summary.order_count == 2
        assert summary.rejected_count == 0

    anyio.run(_run_scenario, scenario)


def test_duplicate_client_order_id_does_not_create_a_second_order() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        first = _plan(orders=(_order(),))
        await store.save_plan(first)

        second = _plan(orders=(_order(),))
        await store.save_plan(second)

        replanned = await reader.order_plan(second.plan_id)
        assert replanned is not None
        assert replanned.orders == ()
        original = await reader.order_plan(first.plan_id)
        assert original is not None
        assert len(original.orders) == 1

    anyio.run(_run_scenario, scenario)


def test_rejected_orders_are_stored_with_reason_and_counted() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        rejected = _order(
            quantity=0,
            state=OrderState.REJECTED,
            reject_code=RiskRule.OPEN_ORDERS.value,
        )
        plan = _plan(orders=(rejected,))

        await store.save_plan(plan)

        (summary,) = await reader.order_plans(_ENVIRONMENT, 10)
        assert summary.order_count == 1
        assert summary.rejected_count == 1
        loaded = await reader.order_plan(plan.plan_id)
        assert loaded is not None
        assert loaded.orders[0].state is OrderState.REJECTED
        assert loaded.orders[0].reject_code == RiskRule.OPEN_ORDERS

    anyio.run(_run_scenario, scenario)


def test_automation_transitions_are_persisted_with_events() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = connection
        assert await store.automation_record(_ENVIRONMENT) is None

        armed = await store.transition_automation(
            AutomationTransition(_ENVIRONMENT, AutomationState.ARMED, "USER", _NOW, _TRADING_DATE)
        )
        running = await store.transition_automation(
            AutomationTransition(
                _ENVIRONMENT,
                AutomationState.RUNNING,
                "USER",
                _NOW + timedelta(minutes=1),
                _TRADING_DATE,
            )
        )

        assert armed.state is AutomationState.ARMED
        assert running.state is AutomationState.RUNNING
        current = await reader.automation(_ENVIRONMENT)
        assert current is not None
        assert current.state is AutomationState.RUNNING
        events = await reader.automation_events(_ENVIRONMENT, 10)
        assert [(event.previous_state, event.state) for event in events] == [
            (AutomationState.ARMED, AutomationState.RUNNING),
            (AutomationState.DISABLED, AutomationState.ARMED),
        ]

    anyio.run(_run_scenario, scenario)


def test_invalid_automation_transition_is_rejected() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = (reader, connection)
        with pytest.raises(InvalidTransitionError):
            _ = await store.transition_automation(
                AutomationTransition(
                    _ENVIRONMENT,
                    AutomationState.RUNNING,
                    "USER",
                    _NOW,
                    _TRADING_DATE,
                )
            )

    anyio.run(_run_scenario, scenario)


def test_api_failures_are_counted_within_the_window() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = (reader, connection)
        await store.record_api_failure(_ENVIRONMENT, "quote:TimeoutError", _NOW)
        await store.record_api_failure(
            _ENVIRONMENT,
            "quote:TimeoutError",
            _NOW - timedelta(minutes=10),
        )

        recent = await store.api_failures_since(_ENVIRONMENT, _NOW - timedelta(minutes=5))
        every = await store.api_failures_since(_ENVIRONMENT, _NOW - timedelta(minutes=30))

        assert recent == 1
        assert every == 2

    anyio.run(_run_scenario, scenario)


def test_account_snapshot_round_trips_and_feeds_nav_baselines() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)

        first = await store.save_account_snapshot(
            _snapshot_observation(nav=Decimal(100_000_000), held=40)
        )
        later = replace(
            _snapshot_observation(nav=Decimal(98_000_000)),
            snapshot=replace(
                _snapshot_observation(nav=Decimal(98_000_000)).snapshot,
                received_at=_NOW + timedelta(minutes=5),
            ),
        )
        _ = await store.save_account_snapshot(later)

        assert await store.session_open_nav(_ENVIRONMENT, _TRADING_DATE) == Decimal(100_000_000)
        assert await store.peak_nav(_ENVIRONMENT) == Decimal(100_000_000)

        snapshots = await reader.account_snapshots(_ENVIRONMENT, 10)
        assert [item.snapshot.nav for item in snapshots] == [
            Decimal(98_000_000),
            Decimal(100_000_000),
        ]
        assert [str(item.snapshot.nav) for item in snapshots] == ["98000000", "100000000"]
        stored_first = next(item for item in snapshots if item.snapshot_id == first.snapshot_id)
        assert str(stored_first.snapshot.cash_balance) == "96000000"
        (position,) = stored_first.snapshot.positions
        assert position.symbol == _SYMBOL
        assert position.quantity == 40
        assert stored_first.snapshot.account_reference == "abc123def456"

    anyio.run(_run_scenario, scenario)


def test_counters_reflect_stored_orders() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = (reader,)
        _ = await _ensure_instrument(connection, _SYMBOL)
        await store.save_plan(
            _plan(
                orders=(
                    _order(),
                    _order(
                        sequence=2,
                        client_order_id="c" * 32,
                        quantity=0,
                        state=OrderState.REJECTED,
                        reject_code=RiskRule.MIN_CASH.value,
                    ),
                )
            )
        )

        counters = await store.counters(_ENVIRONMENT, _TRADING_DATE)

        assert counters.daily_order_attempts == 2
        assert counters.daily_buy_amount == Decimal(5_000_000)
        assert counters.open_orders == 0
        assert counters.unreconciled_orders is False
        assert counters.consecutive_rejects == 1

    anyio.run(_run_scenario, scenario)


def test_orders_are_listed_newest_first_across_plans() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        first = _plan(orders=(_order(),))
        await store.save_plan(first)
        later = replace(
            _plan(orders=(_order(client_order_id="d" * 32, sequence=1),)),
            planned_at=_NOW + timedelta(minutes=3),
        )
        await store.save_plan(later)

        entries = await reader.orders(_ENVIRONMENT, 10)

        assert [entry.client_order_id for entry in entries] == ["d" * 32, "a" * 32]
        assert [entry.plan_id for entry in entries] == [later.plan_id, first.plan_id]
        assert [entry.trading_date for entry in entries] == [_TRADING_DATE, _TRADING_DATE]
        assert [entry.filled_quantity for entry in entries] == [0, 0]
        assert [entry.symbol for entry in entries] == [_SYMBOL, _SYMBOL]
        assert [entry.state for entry in entries] == [OrderState.PLANNED, OrderState.PLANNED]
        assert [str(entry.limit_price) for entry in entries] == [
            "100000.00000000",
            "100000.00000000",
        ]

    anyio.run(_run_scenario, scenario)


def test_risk_state_collects_nav_baselines_counters_and_recent_api_failures() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        now = datetime.now(UTC)
        await store.record_api_failure(_ENVIRONMENT, "quote:TimeoutError", now)
        await store.record_api_failure(
            _ENVIRONMENT,
            "quote:TimeoutError",
            now - timedelta(minutes=10),
        )
        _ = await store.save_account_snapshot(
            _snapshot_observation(nav=Decimal(100_000_000), held=40)
        )
        _ = await store.save_account_snapshot(
            replace(
                _snapshot_observation(nav=Decimal(98_000_000), held=40),
                snapshot=replace(
                    _snapshot_observation(nav=Decimal(98_000_000), held=40).snapshot,
                    received_at=_NOW + timedelta(minutes=5),
                ),
            )
        )
        await store.save_plan(
            _plan(
                orders=(
                    _order(),
                    _order(
                        sequence=2,
                        client_order_id="e" * 32,
                        quantity=0,
                        state=OrderState.REJECTED,
                        reject_code=RiskRule.MIN_CASH.value,
                    ),
                )
            )
        )

        state = await reader.risk_state(_ENVIRONMENT, 300)

        assert state.snapshot is not None
        assert str(state.snapshot.snapshot.nav) == "98000000"
        assert state.basis_date == _TRADING_DATE
        assert str(state.session_open_nav) == "100000000"
        assert str(state.peak_nav) == "100000000"
        assert state.max_order_amount == Decimal(5_000_000)
        assert state.counters.daily_order_attempts == 2
        assert state.counters.daily_buy_amount == Decimal(5_000_000)
        assert state.counters.consecutive_rejects == 1
        assert state.api_failures == 1
        assert state.evaluated_at >= now

    anyio.run(_run_scenario, scenario)


def test_risk_state_without_snapshot_reports_no_basis() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = (store, connection)

        state = await reader.risk_state(_ENVIRONMENT, 300)

        assert state.snapshot is None
        assert state.basis_date is None
        assert state.session_open_nav is None
        assert state.peak_nav is None
        assert state.max_order_amount == Decimal(0)
        assert state.counters.open_orders == 0
        assert state.api_failures == 0

    anyio.run(_run_scenario, scenario)


def test_submission_records_broker_identifiers_and_state_transition() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        plan = _plan(orders=(_order(),))
        await store.save_plan(plan)
        (pending,) = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, plan.plan_id)
        assert pending.state is OrderState.PLANNED

        await store.record_submission(pending.order_id, _acknowledgement(), _NOW)

        (submitted,) = await store.open_orders(_ENVIRONMENT, _TRADING_DATE)
        assert submitted.state is OrderState.SUBMITTED
        assert submitted.broker_order_id == "0000117057"
        assert submitted.broker_org_no == "00950"
        assert await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, plan.plan_id) == ()
        (entry,) = await reader.orders(_ENVIRONMENT, 10)
        assert entry.state is OrderState.SUBMITTED
        assert entry.broker_order_id == "0000117057"
        assert entry.submitted_at == _NOW

    anyio.run(_run_scenario, scenario)


def test_rejected_submission_stores_the_broker_message_code() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        plan = _plan(orders=(_order(),))
        await store.save_plan(plan)
        (pending,) = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, None)

        await store.record_rejection(pending.order_id, _acknowledgement(accepted=False), _NOW)

        loaded = await reader.order_plan(plan.plan_id)
        assert loaded is not None
        assert loaded.orders[0].state is OrderState.REJECTED
        assert loaded.orders[0].reject_code == "APBK0919"
        assert await store.open_orders(_ENVIRONMENT, _TRADING_DATE) == ()

    anyio.run(_run_scenario, scenario)


def test_applied_fill_updates_quantity_price_and_event_log() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        plan = _plan(orders=(_order(quantity=3),))
        await store.save_plan(plan)
        (pending,) = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, None)
        await store.record_submission(pending.order_id, _acknowledgement(), _NOW)

        await store.apply_fill(
            pending.order_id,
            OrderState.PARTIALLY_FILLED,
            1,
            Decimal("71800.00000000"),
            _NOW + timedelta(minutes=1),
        )

        (order,) = await store.open_orders(_ENVIRONMENT, _TRADING_DATE)
        assert order.state is OrderState.PARTIALLY_FILLED
        assert order.filled_quantity == 1
        assert order.average_fill_price == Decimal("71800.00000000")
        (entry,) = await reader.orders(_ENVIRONMENT, 10)
        assert entry.filled_quantity == 1
        assert str(entry.average_fill_price) == "71800.00000000"

    anyio.run(_run_scenario, scenario)


def test_cancel_event_and_reconcile_problem_are_persisted() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        plan = _plan(orders=(_order(),))
        await store.save_plan(plan)
        (pending,) = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, None)
        await store.record_submission(pending.order_id, _acknowledgement(), _NOW)

        await store.record_order_event(
            pending.order_id,
            "cancel_requested",
            "EMERGENCY_STOP",
            _NOW + timedelta(minutes=2),
        )
        await store.record_reconcile_problem(
            _ENVIRONMENT,
            "0000999999",
            ReconcileProblem.UNKNOWN_BROKER_ORDER,
            _NOW + timedelta(minutes=3),
        )

        events = await reader.automation_events(_ENVIRONMENT, 10)
        assert [event.event_type for event in events] == ["reconcile_problem"]
        assert events[0].reason_code == ReconcileProblem.UNKNOWN_BROKER_ORDER.value
        assert events[0].detail == "0000999999"

    anyio.run(_run_scenario, scenario)


def test_pending_exposure_sums_unfilled_quantity_times_limit_price() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = reader
        _ = await _ensure_instrument(connection, _SYMBOL)
        await store.save_plan(_plan(orders=(_order(quantity=3),)))
        (pending,) = await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, None)

        before = await store.pending_exposure(_ENVIRONMENT, _TRADING_DATE)
        assert before == (PendingExposure(symbol=_SYMBOL, amount=Decimal(300_000)),)

        await store.record_submission(pending.order_id, _acknowledgement(), _NOW)
        await store.apply_fill(
            pending.order_id,
            OrderState.PARTIALLY_FILLED,
            1,
            _PRICE,
            _NOW + timedelta(minutes=1),
        )

        after = await store.pending_exposure(_ENVIRONMENT, _TRADING_DATE)
        assert after == (PendingExposure(symbol=_SYMBOL, amount=Decimal(200_000)),)

        await store.apply_fill(
            pending.order_id,
            OrderState.FILLED,
            3,
            _PRICE,
            _NOW + timedelta(minutes=2),
        )
        assert await store.pending_exposure(_ENVIRONMENT, _TRADING_DATE) == ()

    anyio.run(_run_scenario, scenario)


def test_withdrawn_plan_cancels_planned_orders_and_frees_exposure() -> None:
    async def scenario(
        store: PostgresTradingStore,
        reader: PostgresTradingReader,
        connection: AsyncConnection,
    ) -> None:
        _ = await _ensure_instrument(connection, _SYMBOL)
        plan = _plan(orders=(_order(), _order(sequence=2, client_order_id="w" * 32)))
        await store.save_plan(plan)

        withdrawn = await store.withdraw_planned_orders(plan.plan_id, "USER_COMMAND", _NOW)

        assert withdrawn == 2
        assert await store.pending_orders(_ENVIRONMENT, _TRADING_DATE, plan.plan_id) == ()
        assert await store.pending_exposure(_ENVIRONMENT, _TRADING_DATE) == ()
        loaded = await reader.order_plan(plan.plan_id)
        assert loaded is not None
        assert [order.state for order in loaded.orders] == [
            OrderState.CANCELED,
            OrderState.CANCELED,
        ]

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: StoreScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await _purge_environment(connection)
        store = PostgresTradingStore.from_connection(connection)
        reader = PostgresTradingReader.from_connection(connection)
        try:
            await scenario(store, reader, connection)
        finally:
            await store.close()
            await reader.close()
            await transaction.rollback()
    await engine.dispose()


async def _purge_environment(connection: AsyncConnection) -> None:
    """이 트랜잭션 안에서만 환경 데이터를 비운다. 실제 실행 기록은 롤백으로 복원된다."""
    for table in (OrderPlanRow, AutomationEventRow, AutomationStateRow, AccountSnapshotRow):
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
            name="주문 계획 통합 테스트 종목",
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
