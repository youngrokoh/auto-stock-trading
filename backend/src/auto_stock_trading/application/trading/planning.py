from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarVerificationState,
    MarketSessionStatus,
    MarketSessionType,
    calendar_session_status,
    calendar_verification_state,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderIdentity,
    OrderState,
    OrderType,
    client_order_id,
)
from auto_stock_trading.domain.orders.records import (
    AutomationRecord,
    OrderPlanRecord,
    OrderRecord,
    StoredCounters,
)
from auto_stock_trading.domain.risk.engine import (
    AccountState,
    MarketQuote,
    PendingExposure,
    PlannedOrder,
    PlanRequest,
    PositionState,
    SessionCounters,
    SignalCandidate,
    evaluate_plan,
)
from auto_stock_trading.domain.risk.limits import PAPER_RISK_LIMITS

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.calendar import MarketCalendarRecord
    from auto_stock_trading.domain.market_data.models import Instrument, QuoteObservation
    from auto_stock_trading.domain.orders.account import (
        AccountSnapshot,
        AccountSnapshotObservation,
    )
    from auto_stock_trading.domain.orders.records import StoredAccountSnapshot
    from auto_stock_trading.domain.risk.limits import RiskLimits

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_STATUS_CREATED: Final = "created"
_STATUS_BLOCKED: Final = "blocked"
_TRADING_DAY_CHANGED: Final = "TRADING_DAY_CHANGED"
_QUOTE_SOURCE: Final = "KIS"


@dataclass(frozen=True, slots=True)
class AutomationTransition:
    environment: str
    requested: AutomationState
    reason_code: str
    occurred_at: datetime
    trading_date: date | None


class PlanCalendar(Protocol):
    async def session(self, key: CalendarSessionKey) -> MarketCalendarRecord | None: ...


class InstrumentReader(Protocol):
    async def instrument(self, symbol: str) -> Instrument | None: ...


class QuoteSource(Protocol):
    async def fetch_quote(self, target: InstrumentTarget) -> QuoteObservation: ...


class AccountSource(Protocol):
    async def fetch_balance(self) -> AccountSnapshotObservation: ...


class TradingStore(Protocol):
    async def automation_record(self, environment: str) -> AutomationRecord | None: ...

    async def transition_automation(
        self,
        transition: AutomationTransition,
    ) -> AutomationRecord: ...

    async def record_api_failure(
        self,
        environment: str,
        detail: str,
        occurred_at: datetime,
    ) -> None: ...

    async def api_failures_since(self, environment: str, since: datetime) -> int: ...

    async def save_account_snapshot(
        self,
        observation: AccountSnapshotObservation,
    ) -> StoredAccountSnapshot: ...

    async def session_open_nav(self, environment: str, trading_date: date) -> Decimal | None: ...

    async def peak_nav(self, environment: str) -> Decimal | None: ...

    async def counters(self, environment: str, trading_date: date) -> StoredCounters: ...

    async def pending_exposure(
        self,
        environment: str,
        trading_date: date,
    ) -> tuple[PendingExposure, ...]: ...

    async def save_plan(self, plan: OrderPlanRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class PlanInput:
    environment: str
    strategy_name: str
    strategy_version: str
    parameters_json: str
    signal_date: date
    candidates: tuple[SignalCandidate, ...]


_EMPTY_ACCOUNT: Final = AccountState(
    nav=Decimal(0),
    settled_cash=Decimal(0),
    orderable_cash=Decimal(0),
    session_open_nav=Decimal(0),
    peak_nav=Decimal(0),
    positions=(),
    reconciled=False,
)
_EMPTY_COUNTERS: Final = StoredCounters(
    open_orders=0,
    daily_order_attempts=0,
    daily_buy_amount=Decimal(0),
    consecutive_rejects=0,
    unreconciled_orders=True,
)


def _session_key(trading_date: date) -> CalendarSessionKey:
    return CalendarSessionKey(_COUNTRY, _EXCHANGE, trading_date, MarketSessionType.REGULAR)


def _account_state(
    snapshot: AccountSnapshot,
    session_open_nav: Decimal | None,
    peak_nav: Decimal | None,
    *,
    reconciled: bool,
) -> AccountState:
    return AccountState(
        nav=snapshot.nav,
        settled_cash=snapshot.orderable_cash,
        orderable_cash=snapshot.orderable_cash,
        session_open_nav=snapshot.nav if session_open_nav is None else session_open_nav,
        peak_nav=snapshot.nav if peak_nav is None else peak_nav,
        positions=tuple(
            PositionState(
                symbol=position.symbol,
                quantity=position.quantity,
                orderable_quantity=position.orderable_quantity,
                evaluation_amount=position.evaluation_amount,
            )
            for position in snapshot.positions
        ),
        reconciled=reconciled,
    )


def _reconciled(snapshot: AccountSnapshot, counters: StoredCounters) -> bool:
    """미체결 대조가 끝났고 우리 NAV가 증권사 순자산금액과 일치할 때만 조정 완료다."""
    return not counters.unreconciled_orders and snapshot.nav == snapshot.broker_net_asset


def _order_record(request: PlanInput, order: PlannedOrder) -> OrderRecord:
    identity = OrderIdentity(
        strategy_name=request.strategy_name,
        strategy_version=request.strategy_version,
        signal_date=request.signal_date,
        symbol=order.symbol,
        side=order.side,
        sequence=order.sequence,
    )
    return OrderRecord(
        client_order_id=client_order_id(identity),
        sequence=order.sequence,
        symbol=order.symbol,
        side=order.side,
        order_type=OrderType.LIMIT,
        quantity=order.quantity,
        limit_price=order.limit_price,
        reference_price=order.reference_price,
        reference_source=None if order.reference_price is None else _QUOTE_SOURCE,
        reference_received_at=order.reference_received_at,
        state=OrderState.PLANNED if order.reject_code is None else OrderState.REJECTED,
        reject_code=order.reject_code,
        decisions=order.decisions,
    )


@dataclass(frozen=True, slots=True)
class OrderPlanner:
    calendar: PlanCalendar
    instruments: InstrumentReader
    quotes: QuoteSource
    accounts: AccountSource
    store: TradingStore
    limits: RiskLimits = PAPER_RISK_LIMITS

    async def plan(self, request: PlanInput, now: datetime) -> OrderPlanRecord:
        trading_date = now.astimezone(_SEOUL).date()
        automation = await self._automation_for_day(request.environment, trading_date, now)
        trading_day = await self._is_trading_day(trading_date)
        collect = automation.state is AutomationState.RUNNING and trading_day
        stored_snapshot = await self._snapshot(request.environment, now) if collect else None
        counters = (
            await self.store.counters(request.environment, trading_date)
            if collect
            else _EMPTY_COUNTERS
        )
        quotes = await self._quotes(request, now) if collect else ()
        pending = (
            await self.store.pending_exposure(request.environment, trading_date) if collect else ()
        )
        account = (
            _EMPTY_ACCOUNT
            if stored_snapshot is None
            else _account_state(
                stored_snapshot.snapshot,
                await self.store.session_open_nav(request.environment, trading_date),
                await self.store.peak_nav(request.environment),
                reconciled=_reconciled(stored_snapshot.snapshot, counters),
            )
        )
        failures = await self.store.api_failures_since(
            request.environment,
            now - timedelta(seconds=self.limits.api_failure_window_seconds),
        )
        evaluation = evaluate_plan(
            PlanRequest(
                candidates=request.candidates,
                account=account,
                quotes=quotes,
                counters=SessionCounters(
                    open_orders=counters.open_orders,
                    daily_order_attempts=counters.daily_order_attempts,
                    daily_buy_amount=counters.daily_buy_amount,
                    consecutive_rejects=counters.consecutive_rejects,
                    api_failures=failures,
                ),
                automation_state=automation.state,
                trading_day=trading_day,
                now=now,
                limits=self.limits,
                pending=pending,
            )
        )
        if evaluation.pause_rule is not None:
            automation = await self.store.transition_automation(
                AutomationTransition(
                    environment=request.environment,
                    requested=AutomationState.PAUSED,
                    reason_code=evaluation.pause_rule.value,
                    occurred_at=now,
                    trading_date=trading_date,
                )
            )
        plan = OrderPlanRecord(
            plan_id=uuid4(),
            environment=request.environment,
            strategy_name=request.strategy_name,
            strategy_version=request.strategy_version,
            parameters_json=request.parameters_json,
            signal_date=request.signal_date,
            trading_date=trading_date,
            account_snapshot_id=None if stored_snapshot is None else stored_snapshot.snapshot_id,
            nav_basis=None if stored_snapshot is None else stored_snapshot.snapshot.nav,
            session_open_nav=None if stored_snapshot is None else account.session_open_nav,
            automation_state=automation.state,
            status=_STATUS_BLOCKED if evaluation.block_code is not None else _STATUS_CREATED,
            block_code=evaluation.block_code,
            planned_at=now,
            orders=tuple(_order_record(request, order) for order in evaluation.orders),
        )
        await self.store.save_plan(plan)
        return plan

    async def _automation_for_day(
        self,
        environment: str,
        trading_date: date,
        now: datetime,
    ) -> AutomationRecord:
        stored = await self.store.automation_record(environment)
        automation = stored or AutomationRecord(
            environment=environment,
            state=AutomationState.DISABLED,
            reason_code=None,
            trading_date=None,
            changed_at=now,
        )
        stale_day = (
            automation.trading_date is not None
            and automation.trading_date != trading_date
            and automation.state is not AutomationState.DISABLED
        )
        if not stale_day:
            return automation
        return await self.store.transition_automation(
            AutomationTransition(
                environment=environment,
                requested=AutomationState.DISABLED,
                reason_code=_TRADING_DAY_CHANGED,
                occurred_at=now,
                trading_date=trading_date,
            )
        )

    async def _is_trading_day(self, trading_date: date) -> bool:
        record = await self.calendar.session(_session_key(trading_date))
        if record is None:
            return False
        if calendar_verification_state(record.verification) is CalendarVerificationState.CONFLICT:
            return False
        return calendar_session_status(record.session) is not MarketSessionStatus.CLOSED

    async def _snapshot(
        self,
        environment: str,
        now: datetime,
    ) -> StoredAccountSnapshot | None:
        try:
            observation = await self.accounts.fetch_balance()
        except Exception as error:
            await self.store.record_api_failure(
                environment,
                f"account_balance:{type(error).__name__}",
                now,
            )
            raise
        return await self.store.save_account_snapshot(observation)

    async def _quotes(self, request: PlanInput, now: datetime) -> tuple[MarketQuote, ...]:
        quotes: list[MarketQuote] = []
        for symbol in dict.fromkeys(candidate.symbol for candidate in request.candidates):
            instrument = await self.instruments.instrument(symbol)
            if instrument is None:
                continue
            try:
                observation = await self.quotes.fetch_quote(
                    InstrumentTarget(symbol, instrument.product_type)
                )
            except Exception as error:
                await self.store.record_api_failure(
                    request.environment,
                    f"quote:{type(error).__name__}",
                    now,
                )
                raise
            quotes.append(
                MarketQuote(
                    symbol=symbol,
                    product_type=instrument.product_type,
                    price=observation.quote.price,
                    received_at=observation.quote.received_at,
                    trading_status=instrument.trading_status,
                    sector=None,
                )
            )
        return tuple(quotes)
