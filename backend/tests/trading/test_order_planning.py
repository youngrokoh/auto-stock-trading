from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.application.trading.planning import (
    AutomationTransition,
    OrderPlanner,
    PlanInput,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarSource,
    ClosedMarketSession,
    ConfirmedVerification,
    MarketCalendarRecord,
    MarketSessionType,
    OpenMarketSession,
    SessionWindow,
)
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    Instrument,
    ProductType,
    Quote,
    QuoteObservation,
    RawBrokerResponse,
)
from auto_stock_trading.domain.orders.account import (
    AccountPosition,
    AccountSnapshot,
    AccountSnapshotObservation,
)
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide, OrderState
from auto_stock_trading.domain.orders.records import (
    AutomationRecord,
    StoredAccountSnapshot,
    StoredCounters,
)
from auto_stock_trading.domain.risk.engine import PendingExposure, SignalCandidate
from auto_stock_trading.domain.risk.limits import BlockCode, RiskRule

if TYPE_CHECKING:
    from uuid import UUID

    from auto_stock_trading.domain.market_data.models import InstrumentTarget
    from auto_stock_trading.domain.orders.records import OrderPlanRecord

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TRADING_DATE: Final = date(2026, 8, 18)
_NOW: Final = datetime.combine(_TRADING_DATE, time(10, 0), _SEOUL)
_ENVIRONMENT: Final = "paper"
_SYMBOL: Final = "005930"
_PRICE: Final = Decimal(100_000)
_NAV: Final = Decimal(100_000_000)
_PLAN_INPUT: Final = PlanInput(
    environment=_ENVIRONMENT,
    strategy_name="ma-rsi",
    strategy_version="1",
    parameters_json='{"short_period":5}',
    signal_date=_TRADING_DATE,
    candidates=(SignalCandidate(_SYMBOL, OrderSide.BUY),),
)


def _calendar_record(*, closed: bool) -> MarketCalendarRecord:
    key = CalendarSessionKey("KR", "XKRX", _TRADING_DATE, MarketSessionType.REGULAR)
    session = (
        ClosedMarketSession(key, "휴장")
        if closed
        else OpenMarketSession(
            key,
            SessionWindow(
                datetime.combine(_TRADING_DATE, time(9, 0), _SEOUL),
                datetime.combine(_TRADING_DATE, time(15, 30), _SEOUL),
            ),
        )
    )
    return MarketCalendarRecord(
        id=uuid4(),
        session=session,
        exchange_timezone="Asia/Seoul",
        source=CalendarSource("KRX", "https://example.test/calendar", date(2026, 1, 1)),
        received_at=_NOW,
        verification=ConfirmedVerification(_NOW),
        version=1,
        valid_from=_NOW,
        superseded_at=None,
        raw_response_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
    )


@dataclass
class FakeCalendar:
    closed: bool = False
    missing: bool = False

    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None:
        _ = key
        return None if self.missing else _calendar_record(closed=self.closed)


@dataclass
class FakeInstruments:
    async def instrument(self, symbol: str) -> Instrument | None:
        return Instrument(
            country="KR",
            exchange="KRX",
            symbol=symbol,
            product_type=ProductType.STOCK,
            currency="KRW",
            name="삼성전자",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="active",
            source="KIS",
            source_as_of=_TRADING_DATE,
        )


@dataclass
class FakeQuotes:
    calls: int = 0
    fails: bool = False
    age_seconds: int = 1

    async def fetch_quote(self, target: InstrumentTarget) -> QuoteObservation:
        self.calls += 1
        if self.fails:
            raise TimeoutError
        received_at = _NOW - timedelta(seconds=self.age_seconds)
        return QuoteObservation(
            quote=Quote(
                symbol=target.symbol,
                price=_PRICE,
                open_price=_PRICE,
                high_price=_PRICE,
                low_price=_PRICE,
                previous_close=_PRICE,
                change=Decimal(0),
                change_percent=Decimal(0),
                volume=1,
                trading_value=_PRICE,
                currency="KRW",
                source="KIS",
                as_of=received_at,
                received_at=received_at,
            ),
            raw=RawBrokerResponse(
                operation=BrokerOperation.QUOTE,
                endpoint="/quote",
                request_fingerprint=f"quote:{target.symbol}",
                received_at=received_at,
                payload_json="{}",
            ),
        )


@dataclass
class FakeAccounts:
    calls: int = 0
    fails: bool = False
    nav: Decimal = _NAV
    held_quantity: int = 0
    broker_net_asset: Decimal | None = None
    # 증권사 요약의 평가합계. 장중에는 보유 행 합계와 시세 시점이 달라 값이 어긋난다.
    broker_position_value: Decimal | None = None

    async def fetch_balance(self) -> AccountSnapshotObservation:
        self.calls += 1
        if self.fails:
            raise TimeoutError
        position_value = _PRICE * self.held_quantity
        positions = (
            ()
            if self.held_quantity == 0
            else (
                AccountPosition(
                    symbol=_SYMBOL,
                    quantity=self.held_quantity,
                    orderable_quantity=self.held_quantity,
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
            cash_balance=self.nav - position_value,
            orderable_cash=self.nav - position_value,
            position_value=position_value,
            nav=self.nav,
            broker_position_value=(
                position_value if self.broker_position_value is None else self.broker_position_value
            ),
            broker_net_asset=self.nav if self.broker_net_asset is None else self.broker_net_asset,
            trading_date=_TRADING_DATE,
            as_of=_NOW,
            received_at=_NOW,
            positions=positions,
        )
        return AccountSnapshotObservation(
            snapshot=snapshot,
            raw=RawBrokerResponse(
                operation=BrokerOperation.ACCOUNT_BALANCE,
                endpoint="/balance",
                request_fingerprint="account_balance:abc123def456",
                received_at=_NOW,
                payload_json="{}",
            ),
        )


@dataclass
class FakeStore:
    no_capacity: list[tuple[str, str]] = field(default_factory=list)
    automation: AutomationRecord | None = None
    stored_counters: StoredCounters = field(
        default_factory=lambda: StoredCounters(
            open_orders=0,
            daily_order_attempts=0,
            daily_buy_amount=Decimal(0),
            consecutive_rejects=0,
            unreconciled_orders=False,
        )
    )
    session_open: Decimal | None = None
    peak: Decimal | None = None
    pending: tuple[PendingExposure, ...] = ()
    failures: int = 0
    skipped_orders: int = 0
    transitions: list[AutomationTransition] = field(default_factory=list[AutomationTransition])
    api_failures: list[str] = field(default_factory=list[str])
    plans: list[OrderPlanRecord] = field(default_factory=list["OrderPlanRecord"])

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        _ = environment
        return self.automation

    async def transition_automation(self, transition: AutomationTransition) -> AutomationRecord:
        self.transitions.append(transition)
        record = AutomationRecord(
            environment=transition.environment,
            state=transition.requested,
            reason_code=transition.reason_code,
            trading_date=transition.trading_date,
            changed_at=transition.occurred_at,
        )
        self.automation = record
        return record

    async def record_no_capacity(
        self,
        environment: str,
        symbol: str,
        rule_code: str,
        trading_date: date,
        occurred_at: datetime,
    ) -> bool:
        _ = (environment, trading_date, occurred_at)
        key = (symbol, rule_code)
        if key in self.no_capacity:
            return False
        self.no_capacity.append(key)
        return True

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        _ = (environment, occurred_at)
        self.api_failures.append(detail)

    async def api_failures_since(self, environment: str, since: datetime) -> int:
        _ = (environment, since)
        return self.failures

    async def pending_exposure(
        self,
        environment: str,
        trading_date: date,
        exclude_order_id: UUID | None = None,
    ) -> tuple[PendingExposure, ...]:
        _ = (environment, trading_date, exclude_order_id)
        return self.pending

    async def save_account_snapshot(
        self,
        observation: AccountSnapshotObservation,
    ) -> StoredAccountSnapshot:
        return StoredAccountSnapshot(snapshot_id=uuid4(), snapshot=observation.snapshot)

    async def session_open_nav(self, environment: str, trading_date: date) -> Decimal | None:
        _ = (environment, trading_date)
        return self.session_open

    async def peak_nav(self, environment: str) -> Decimal | None:
        _ = environment
        return self.peak

    async def counters(self, environment: str, trading_date: date) -> StoredCounters:
        _ = (environment, trading_date)
        return self.stored_counters

    async def save_plan(self, plan: OrderPlanRecord) -> None:
        self.plans.append(plan)

    async def stored_order_count(self, plan_id: UUID) -> int:
        """중복 식별자로 저장이 생략된 주문 수를 재현하려면 `skipped_orders`를 올린다."""
        stored = [plan for plan in self.plans if plan.plan_id == plan_id]
        return sum(len(plan.orders) for plan in stored) - self.skipped_orders


@dataclass
class _Harness:
    planner: OrderPlanner
    calendar: FakeCalendar
    quotes: FakeQuotes
    accounts: FakeAccounts
    store: FakeStore


def _automation(
    state: AutomationState = AutomationState.RUNNING,
    trading_date: date | None = _TRADING_DATE,
) -> AutomationRecord:
    return AutomationRecord(
        environment=_ENVIRONMENT,
        state=state,
        reason_code=None,
        trading_date=trading_date,
        changed_at=_NOW,
    )


@final
@dataclass
class FakeSectors:
    """업종 사실 원천. 값이 없는 종목은 미분류로 남는다."""

    sectors: dict[str, str] = field(default_factory=lambda: {_SYMBOL: "5"})

    async def sector(self, symbol: str) -> str | None:
        return self.sectors.get(symbol)


@dataclass(frozen=True, slots=True)
class _Collaborators:
    """테스트가 바꾸고 싶은 것만 넘기는 묶음."""

    automation: AutomationRecord | None = None
    calendar: FakeCalendar | None = None
    quotes: FakeQuotes | None = None
    accounts: FakeAccounts | None = None
    store: FakeStore | None = None
    sectors: FakeSectors | None = None


def _harness(collaborators: _Collaborators | None = None) -> _Harness:
    given = collaborators or _Collaborators()
    automation = given.automation
    calendar = given.calendar
    quotes = given.quotes
    accounts = given.accounts
    store = given.store
    sectors = given.sectors
    fake_calendar = calendar or FakeCalendar()
    fake_quotes = quotes or FakeQuotes()
    fake_accounts = accounts or FakeAccounts()
    fake_store = store or FakeStore()
    fake_store.automation = automation or _automation()
    planner = OrderPlanner(
        calendar=fake_calendar,
        instruments=FakeInstruments(),
        quotes=fake_quotes,
        accounts=fake_accounts,
        store=fake_store,
        sectors=sectors or FakeSectors(),
    )
    return _Harness(planner, fake_calendar, fake_quotes, fake_accounts, fake_store)


def test_running_session_creates_planned_orders_with_lineage() -> None:
    harness = _harness()

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.status == "created"
    assert plan.block_code is None
    assert plan.nav_basis == _NAV
    assert plan.account_snapshot_id is not None
    assert [(order.quantity, order.state) for order in plan.orders] == [
        (50, OrderState.PLANNED),
        (50, OrderState.PLANNED),
    ]
    first = plan.orders[0]
    assert first.limit_price == _PRICE
    assert first.reference_source == "KIS"
    assert first.reference_received_at is not None
    assert first.decisions
    # 저장된 레코드는 저장 결과(stored_orders)만 다르다.
    assert harness.store.plans == [replace(plan, stored_orders=None)]


def test_replanning_the_same_signal_reuses_client_order_ids() -> None:
    harness = _harness()

    first = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)
    second = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert [order.client_order_id for order in first.orders] == [
        order.client_order_id for order in second.orders
    ]
    assert first.plan_id != second.plan_id


@pytest.mark.parametrize(
    "state",
    [AutomationState.DISABLED, AutomationState.ARMED, AutomationState.PAUSED],
)
def test_non_running_automation_blocks_without_external_calls(state: AutomationState) -> None:
    harness = _harness(_Collaborators(automation=_automation(state)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.status == "blocked"
    assert plan.block_code == BlockCode.AUTOMATION_NOT_RUNNING
    assert plan.orders == ()
    assert harness.accounts.calls == 0
    assert harness.quotes.calls == 0


def test_closed_market_blocks_without_external_calls() -> None:
    harness = _harness(_Collaborators(calendar=FakeCalendar(closed=True)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code == BlockCode.MARKET_CLOSED
    assert harness.accounts.calls == 0
    assert harness.quotes.calls == 0


def test_missing_calendar_session_blocks_as_market_closed() -> None:
    harness = _harness(_Collaborators(calendar=FakeCalendar(missing=True)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code == BlockCode.MARKET_CLOSED


def test_unreconciled_open_orders_block_the_plan() -> None:
    store = FakeStore(
        stored_counters=StoredCounters(
            open_orders=1,
            daily_order_attempts=1,
            daily_buy_amount=Decimal(0),
            consecutive_rejects=0,
            unreconciled_orders=True,
        )
    )
    harness = _harness(_Collaborators(store=store))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code == BlockCode.ACCOUNT_NOT_RECONCILED
    assert plan.orders == ()


def test_stale_quote_rejects_the_candidate_but_keeps_the_plan() -> None:
    harness = _harness(_Collaborators(quotes=FakeQuotes(age_seconds=11)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.status == "created"
    (order,) = plan.orders
    assert order.state is OrderState.REJECTED
    assert order.reject_code == BlockCode.DATA_STALE


def test_daily_loss_limit_pauses_automation_and_blocks() -> None:
    store = FakeStore(session_open=Decimal(200_000_000))
    harness = _harness(_Collaborators(store=store))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code == RiskRule.DAILY_LOSS
    assert plan.automation_state is AutomationState.PAUSED
    (transition,) = store.transitions
    assert transition.requested is AutomationState.PAUSED
    assert transition.reason_code == RiskRule.DAILY_LOSS


def test_trading_day_change_returns_automation_to_disabled() -> None:
    store = FakeStore()
    harness = _harness(
        _Collaborators(store=store, automation=_automation(trading_date=date(2026, 8, 14)))
    )

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    (transition,) = store.transitions
    assert transition.requested is AutomationState.DISABLED
    assert transition.reason_code == "TRADING_DAY_CHANGED"
    assert plan.block_code == BlockCode.AUTOMATION_NOT_RUNNING


def test_account_source_failure_records_api_failure_and_propagates() -> None:
    store = FakeStore()
    harness = _harness(_Collaborators(store=store, accounts=FakeAccounts(fails=True)))

    with pytest.raises(TimeoutError):
        _ = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert store.api_failures == ["account_balance:TimeoutError"]
    assert store.plans == []


def test_quote_source_failure_records_api_failure_and_propagates() -> None:
    store = FakeStore()
    harness = _harness(_Collaborators(store=store, quotes=FakeQuotes(fails=True)))

    with pytest.raises(TimeoutError):
        _ = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert store.api_failures == ["quote:TimeoutError"]
    assert store.plans == []


def test_repeated_api_failures_block_the_plan() -> None:
    harness = _harness(_Collaborators(store=FakeStore(failures=3)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code == BlockCode.API_CONSECUTIVE_FAILURE
    assert plan.automation_state is AutomationState.PAUSED


def test_sell_signal_liquidates_held_position_in_split_orders() -> None:
    harness = _harness(_Collaborators(accounts=FakeAccounts(held_quantity=100)))
    request = replace(_PLAN_INPUT, candidates=(SignalCandidate(_SYMBOL, OrderSide.SELL),))

    plan = anyio.run(harness.planner.plan, request, _NOW)

    assert [(order.side, order.quantity) for order in plan.orders] == [
        (OrderSide.SELL, 50),
        (OrderSide.SELL, 50),
    ]
    assert all(order.state is OrderState.PLANNED for order in plan.orders)


def test_sell_signal_without_position_creates_no_order() -> None:
    harness = _harness()
    request = replace(_PLAN_INPUT, candidates=(SignalCandidate(_SYMBOL, OrderSide.SELL),))

    plan = anyio.run(harness.planner.plan, request, _NOW)

    assert plan.orders == ()
    assert plan.status == "created"


def test_pending_orders_from_earlier_plans_consume_the_exposure_cap() -> None:
    """정책 §2대로 이전 계획의 미체결·계획 주문이 예상 노출에 포함돼야 한다."""
    pending = (PendingExposure(symbol=_SYMBOL, amount=_NAV / 10),)
    harness = _harness(_Collaborators(store=FakeStore(pending=pending)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.status == "created"
    # 한도가 다 찼으면 넣을 자리가 없는 것이며 거절 주문을 만들지 않는다(ADR-0020).
    assert plan.orders == ()


def test_the_plan_reports_orders_that_were_actually_stored() -> None:
    """같은 신호를 다시 계획하면 중복 식별자로 저장이 생략된다. 보고는 저장 결과를 센다."""
    harness = _harness()

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.orders
    assert plan.stored_orders == len(plan.orders)


def test_duplicate_identifiers_are_reported_as_not_stored() -> None:
    harness = _harness(_Collaborators(store=FakeStore(skipped_orders=2)))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.stored_orders == len(plan.orders) - 2


def test_a_cash_basis_mismatch_with_the_broker_blocks_as_unreconciled() -> None:
    """정책 §7.2: 판정 현금 + 증권사 평가합계가 순자산금액과 다르면 주문을 만들지 않는다."""
    harness = _harness(_Collaborators(accounts=FakeAccounts(broker_net_asset=_NAV - Decimal(1))))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code == BlockCode.ACCOUNT_NOT_RECONCILED
    assert plan.orders == ()


def test_intraday_valuation_drift_between_holdings_and_summary_does_not_block() -> None:
    """증권사 응답 안에서도 보유 행과 요약의 시세 시점이 달라 평가금액이 어긋난다(실측).

    대조는 판정 현금 + 증권사 평가합계 = 순자산금액으로 하므로 이 차이는 차단 사유가 아니다.
    """
    drift = Decimal(2500)
    accounts = FakeAccounts(
        held_quantity=1,
        broker_position_value=_PRICE + drift,
        broker_net_asset=_NAV + drift,
    )
    harness = _harness(_Collaborators(accounts=accounts))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.block_code != BlockCode.ACCOUNT_NOT_RECONCILED


def test_the_plan_uses_the_stored_sector_key_for_the_sector_limit() -> None:
    """업종 사실이 있으면 업종 한도로 판정한다(정책 §3). 지금까지는 항상 미분류였다."""
    harness = _harness()

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    decisions = {decision.rule for order in plan.orders for decision in order.decisions}
    assert RiskRule.SECTOR_EXPOSURE in decisions
    assert RiskRule.UNCLASSIFIED_EXPOSURE not in decisions


def test_an_instrument_without_a_sector_fact_stays_unclassified() -> None:
    harness = _harness(_Collaborators(sectors=FakeSectors(sectors={})))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    decisions = {decision.rule for order in plan.orders for decision in order.decisions}
    assert RiskRule.UNCLASSIFIED_EXPOSURE in decisions
    assert RiskRule.SECTOR_EXPOSURE not in decisions


def test_a_candidate_without_room_is_recorded_rather_than_rejected() -> None:
    """거절로 세지 않는 대신 사실을 남긴다(ADR-0020 결정 2).

    남기지 않으면 전략이 매일 통과할 수 없는 것을 요구하는 상태가 흔적 없이 지나간다.
    """
    pending = (PendingExposure(symbol=_SYMBOL, amount=_NAV / 10),)
    store = FakeStore(pending=pending)
    harness = _harness(_Collaborators(store=store))

    plan = anyio.run(harness.planner.plan, _PLAN_INPUT, _NOW)

    assert plan.orders == ()
    assert store.no_capacity == [(_SYMBOL, RiskRule.SYMBOL_EXPOSURE.value)]
