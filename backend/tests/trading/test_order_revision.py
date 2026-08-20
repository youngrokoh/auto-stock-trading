from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final
from uuid import UUID, uuid4

import anyio

from auto_stock_trading.adapters.brokers.kis_orders import BrokerAcknowledgement
from auto_stock_trading.application.trading.planning import PlanContext
from auto_stock_trading.application.trading.revision import (
    OrderReviser,
    RevisionInput,
    RevisionRecord,
)
from auto_stock_trading.application.trading.submission import TrackedOrder
from auto_stock_trading.domain.market_data.models import (
    BrokerOperation,
    ProductType,
    RawBrokerResponse,
)
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide, OrderState
from auto_stock_trading.domain.orders.records import AutomationRecord
from auto_stock_trading.domain.risk.engine import (
    AccountState,
    MarketQuote,
    PositionState,
    SessionCounters,
)
from auto_stock_trading.domain.risk.limits import RiskRule

if TYPE_CHECKING:
    from auto_stock_trading.adapters.brokers.kis_orders import ReviseRequest

_NOW: Final = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
_ENVIRONMENT: Final = "paper"
_SYMBOL: Final = "005930"
_ORDER_ID: Final = UUID("55555555-5555-5555-5555-555555555555")
_BROKER_ORDER_ID: Final = "0000030001"
_NEW_BROKER_ORDER_ID: Final = "0000030099"
_NAV: Final = Decimal(20_000_000)
_PRICE: Final = Decimal(250_000)


def _order(
    *,
    quantity: int = 2,
    filled_quantity: int = 0,
    state: OrderState = OrderState.SUBMITTED,
) -> TrackedOrder:
    return TrackedOrder(
        order_id=_ORDER_ID,
        plan_id=uuid4(),
        client_order_id="fixture-client-order-id",
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None,
        limit_price=Decimal(248_000),
        state=state,
        broker_order_id=_BROKER_ORDER_ID,
        broker_org_no="00950",
    )


@dataclass(frozen=True, slots=True)
class _Fixture:
    """판정 입력 조합. 인자를 하나로 묶어 테스트가 필요한 값만 바꾸게 한다."""

    automation: AutomationState = AutomationState.RUNNING
    trading_day: bool = True
    quote_price: Decimal = _PRICE
    quote_age_seconds: int = 0
    trading_status: str = "active"
    nav: Decimal = _NAV


def _plan_context(fixture: _Fixture | None = None) -> PlanContext:
    values = fixture or _Fixture()
    automation = values.automation
    trading_day = values.trading_day
    quote_price = values.quote_price
    quote_age_seconds = values.quote_age_seconds
    trading_status = values.trading_status
    nav = values.nav
    return PlanContext(
        trading_date=_NOW.date(),
        automation=AutomationRecord(
            environment=_ENVIRONMENT,
            state=automation,
            reason_code=None,
            trading_date=_NOW.date(),
            changed_at=_NOW,
        ),
        trading_day=trading_day,
        snapshot=None,
        account=AccountState(
            nav=nav,
            settled_cash=nav,
            orderable_cash=nav,
            session_open_nav=nav,
            peak_nav=nav,
            positions=(
                PositionState(
                    symbol=_SYMBOL,
                    quantity=0,
                    orderable_quantity=0,
                    evaluation_amount=Decimal(0),
                ),
            ),
            reconciled=True,
        ),
        quotes=(
            MarketQuote(
                symbol=_SYMBOL,
                product_type=ProductType.STOCK,
                price=quote_price,
                received_at=_NOW.fromtimestamp(
                    _NOW.timestamp() - quote_age_seconds,
                    tz=UTC,
                ),
                trading_status=trading_status,
                sector=None,
            ),
        ),
        counters=SessionCounters(
            open_orders=0,
            daily_order_attempts=1,
            daily_buy_amount=Decimal(0),
            consecutive_rejects=0,
            api_failures=0,
        ),
        pending=(),
    )


@final
@dataclass
class FakeContextSource:
    prepared: PlanContext = field(default_factory=_plan_context)
    exclusions: list[UUID | None] = field(default_factory=list)
    paused: list[RiskRule] = field(default_factory=list)

    async def context(
        self,
        environment: str,
        symbols: tuple[str, ...],
        now: datetime,
        exclude_order_id: UUID | None = None,
    ) -> PlanContext:
        assert environment == _ENVIRONMENT
        assert symbols == (_SYMBOL,)
        assert now is not None
        self.exclusions.append(exclude_order_id)
        return self.prepared

    async def pause(self, environment: str, rule: RiskRule, now: datetime) -> AutomationRecord:
        assert environment == _ENVIRONMENT
        assert now is not None
        self.paused.append(rule)
        return AutomationRecord(
            environment=environment,
            state=AutomationState.PAUSED,
            reason_code=rule.value,
            trading_date=_NOW.date(),
            changed_at=_NOW,
        )


@final
@dataclass
class FakeBroker:
    accepted: bool = True
    requests: list[ReviseRequest] = field(default_factory=list)

    async def revise(self, request: ReviseRequest) -> BrokerAcknowledgement:
        self.requests.append(request)
        return BrokerAcknowledgement(
            accepted=self.accepted,
            broker_order_id=_NEW_BROKER_ORDER_ID if self.accepted else None,
            broker_org_no="00950" if self.accepted else None,
            broker_order_time="131200" if self.accepted else None,
            message_code="40600000" if self.accepted else "40310000",
            message="정정 완료" if self.accepted else "정정 가능 수량이 없습니다.",
            raw=RawBrokerResponse(
                operation=BrokerOperation.ORDER_CANCEL,
                endpoint="/uapi/domestic-stock/v1/trading/order-rvsecncl",
                request_fingerprint="order_revise:abcdef123456:0000030001",
                received_at=_NOW,
                payload_json='{"rt_cd":"0"}',
            ),
        )


@final
@dataclass
class FakeStore:
    order: TrackedOrder | None = field(default_factory=_order)
    applied: list[tuple[UUID, str, Decimal]] = field(default_factory=list)
    decisions: list[tuple[UUID, int, int]] = field(default_factory=list)
    rejections: list[tuple[UUID, str]] = field(default_factory=list)
    raws: list[str] = field(default_factory=list)
    attempts: int = 2

    async def open_order(self, environment: str, broker_order_id: str) -> TrackedOrder | None:
        assert environment == _ENVIRONMENT
        if self.order is None or self.order.broker_order_id != broker_order_id:
            return None
        return self.order

    async def next_revision_attempt(self, order_id: UUID) -> int:
        assert order_id == _ORDER_ID
        return self.attempts

    async def record_revision(self, record: RevisionRecord) -> None:
        broker_order_id = record.acknowledgement.broker_order_id
        assert broker_order_id is not None
        self.applied.append((record.order_id, broker_order_id, record.limit_price))
        self.decisions.append((record.order_id, record.attempt, len(record.decisions)))

    async def record_revision_rejection(self, record: RevisionRecord) -> None:
        assert record.attempt >= 1
        self.rejections.append((record.order_id, record.acknowledgement.message_code))

    async def save_broker_response(self, raw: RawBrokerResponse) -> None:
        self.raws.append(raw.request_fingerprint)

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None:
        assert environment == _ENVIRONMENT
        assert occurred_at is not None
        self.rejections.append((_ORDER_ID, detail))


def _reviser(
    store: FakeStore,
    broker: FakeBroker,
    context: FakeContextSource,
) -> OrderReviser:
    return OrderReviser(context=context, broker=broker, store=store)


def _request(offset: str = "0.4") -> RevisionInput:
    return RevisionInput(
        environment=_ENVIRONMENT,
        broker_order_id=_BROKER_ORDER_ID,
        price_offset=Decimal(offset) / Decimal(100),
    )


def test_a_checked_revision_updates_the_broker_order_id_and_price() -> None:
    async def run() -> None:
        store = FakeStore()
        broker = FakeBroker()
        context = FakeContextSource()

        result = await _reviser(store, broker, context).revise(_request(), _NOW)

        assert result.applied
        assert result.reject_code is None
        assert result.limit_price == Decimal(251_000)
        assert store.applied == [(_ORDER_ID, _NEW_BROKER_ORDER_ID, Decimal(251_000))]
        assert store.decisions == [(_ORDER_ID, 2, len(result.decisions))]
        assert result.decisions
        # 정정 판정은 대상 주문 자신을 노출·미체결 계산에서 뺀다.
        assert context.exclusions == [_ORDER_ID]
        (sent,) = broker.requests
        assert sent.broker_order_id == _BROKER_ORDER_ID
        assert sent.quantity == 2
        assert sent.limit_price == Decimal(251_000)

    anyio.run(run)


def test_an_unknown_order_is_refused_without_calling_the_broker() -> None:
    async def run() -> None:
        store = FakeStore(order=None)
        broker = FakeBroker()

        result = await _reviser(store, broker, FakeContextSource()).revise(_request(), _NOW)

        assert not result.applied
        assert result.reject_code == "UNKNOWN_ORDER"
        assert broker.requests == []

    anyio.run(run)


def test_a_filled_order_cannot_be_revised() -> None:
    async def run() -> None:
        store = FakeStore(order=_order(filled_quantity=2, state=OrderState.FILLED))
        broker = FakeBroker()

        result = await _reviser(store, broker, FakeContextSource()).revise(_request(), _NOW)

        assert not result.applied
        assert result.reject_code == "NOT_OPEN"
        assert broker.requests == []

    anyio.run(run)


def test_automation_that_is_not_running_blocks_the_revision() -> None:
    async def run() -> None:
        paused = _Fixture(automation=AutomationState.PAUSED)
        context = FakeContextSource(prepared=_plan_context(paused))
        broker = FakeBroker()

        result = await _reviser(FakeStore(), broker, context).revise(_request(), _NOW)

        assert not result.applied
        assert result.reject_code == "AUTOMATION_NOT_RUNNING"
        assert broker.requests == []

    anyio.run(run)


def test_a_stale_reference_price_blocks_the_revision() -> None:
    async def run() -> None:
        context = FakeContextSource(prepared=_plan_context(_Fixture(quote_age_seconds=30)))
        broker = FakeBroker()

        result = await _reviser(FakeStore(), broker, context).revise(_request(), _NOW)

        assert not result.applied
        assert result.reject_code == "DATA_STALE"
        assert broker.requests == []

    anyio.run(run)


def test_an_offset_beyond_the_price_band_blocks_the_revision() -> None:
    async def run() -> None:
        broker = FakeBroker()

        result = await _reviser(FakeStore(), broker, FakeContextSource()).revise(
            _request(offset="2.0"),
            _NOW,
        )

        assert not result.applied
        assert result.reject_code == RiskRule.ORDER_PRICE_BAND.value
        assert broker.requests == []

    anyio.run(run)


def test_a_revision_that_breaks_a_limit_is_refused_with_the_rule_code() -> None:
    """NAV를 낮추면 같은 수량·가격이 주문 1건 한도(NAV 5%)를 넘어 정정도 거절된다."""

    async def run() -> None:
        context = FakeContextSource(prepared=_plan_context(_Fixture(nav=Decimal(5_000_000))))
        broker = FakeBroker()

        result = await _reviser(FakeStore(), broker, context).revise(_request(), _NOW)

        assert not result.applied
        assert result.reject_code is not None
        assert result.reject_code.startswith("RISK_")
        assert broker.requests == []
        assert result.decisions

    anyio.run(run)


def test_a_broker_rejection_keeps_the_order_unchanged() -> None:
    async def run() -> None:
        store = FakeStore()
        broker = FakeBroker(accepted=False)

        result = await _reviser(store, broker, FakeContextSource()).revise(_request(), _NOW)

        assert not result.applied
        assert result.reject_code == "40310000"
        assert store.applied == []
        assert store.rejections == [(_ORDER_ID, "40310000")]

    anyio.run(run)
