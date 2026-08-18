from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.orders.models import AutomationState, OrderSide
from auto_stock_trading.domain.orders.pricing import round_to_tick, within_price_band
from auto_stock_trading.domain.risk.limits import BlockCode, RiskRule

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.models import ProductType
    from auto_stock_trading.domain.risk.limits import RiskLimits

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_ACTIVE_TRADING_STATUS: Final = "active"


@dataclass(frozen=True, slots=True)
class PositionState:
    symbol: str
    quantity: int
    orderable_quantity: int
    evaluation_amount: Decimal


@dataclass(frozen=True, slots=True)
class AccountState:
    nav: Decimal
    cash_balance: Decimal
    orderable_cash: Decimal
    session_open_nav: Decimal
    peak_nav: Decimal
    positions: tuple[PositionState, ...]
    reconciled: bool


@dataclass(frozen=True, slots=True)
class MarketQuote:
    symbol: str
    product_type: ProductType
    price: Decimal
    received_at: datetime
    trading_status: str
    sector: str | None


@dataclass(frozen=True, slots=True)
class SessionCounters:
    open_orders: int
    daily_order_attempts: int
    daily_buy_amount: Decimal
    consecutive_rejects: int
    api_failures: int


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    symbol: str
    side: OrderSide


@dataclass(frozen=True, slots=True)
class PlanRequest:
    candidates: tuple[SignalCandidate, ...]
    account: AccountState
    quotes: tuple[MarketQuote, ...]
    counters: SessionCounters
    automation_state: AutomationState
    trading_day: bool
    now: datetime
    limits: RiskLimits


@dataclass(frozen=True, slots=True)
class RiskDecision:
    rule: RiskRule
    limit_value: Decimal
    projected_value: Decimal
    passed: bool


@dataclass(frozen=True, slots=True)
class PlannedOrder:
    sequence: int
    symbol: str
    side: OrderSide
    quantity: int
    limit_price: Decimal | None
    reference_price: Decimal | None
    reference_received_at: datetime | None
    reject_code: str | None
    decisions: tuple[RiskDecision, ...]


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    orders: tuple[PlannedOrder, ...]
    block_code: str | None
    pause_rule: RiskRule | None


@dataclass(frozen=True, slots=True)
class _Cap:
    rule: RiskRule
    limit_value: Decimal
    base: Decimal
    available: Decimal
    decreasing: bool = False

    def projected(self, order_value: Decimal) -> Decimal:
        return self.base - order_value if self.decreasing else self.base + order_value

    def decision(self, order_value: Decimal) -> RiskDecision:
        projected = self.projected(order_value)
        passed = projected >= self.limit_value if self.decreasing else projected <= self.limit_value
        return RiskDecision(
            rule=self.rule,
            limit_value=self.limit_value,
            projected_value=projected,
            passed=passed,
        )


@dataclass(slots=True)
class _PlanState:
    symbol_value: dict[str, Decimal] = field(default_factory=dict[str, Decimal])
    sector_value: dict[str, Decimal] = field(default_factory=dict[str, Decimal])
    unclassified_value: Decimal = Decimal(0)
    total_value: Decimal = Decimal(0)
    spend: Decimal = Decimal(0)
    buy_amount: Decimal = Decimal(0)
    created: int = 0
    sequence: int = 0

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence


def _within_order_window(request: PlanRequest) -> bool:
    clock = request.now.astimezone(_SEOUL).time()
    return request.limits.order_window_start <= clock <= request.limits.order_window_end


def _pause_rule(request: PlanRequest) -> RiskRule | None:
    account = request.account
    counters = request.counters
    limits = request.limits
    if account.session_open_nav > 0 and (
        account.nav / account.session_open_nav - 1 <= limits.daily_loss
    ):
        return RiskRule.DAILY_LOSS
    if account.peak_nav > 0 and account.nav / account.peak_nav - 1 <= limits.drawdown:
        return RiskRule.DRAWDOWN
    if counters.daily_order_attempts >= limits.daily_order_attempts:
        return RiskRule.DAILY_ORDER_ATTEMPTS
    if counters.consecutive_rejects >= limits.consecutive_rejects:
        return RiskRule.CONSECUTIVE_REJECTS
    return None


def _gate(request: PlanRequest) -> tuple[str | None, RiskRule | None]:
    if request.automation_state is not AutomationState.RUNNING:
        return BlockCode.AUTOMATION_NOT_RUNNING.value, None
    if request.counters.api_failures >= request.limits.api_failures:
        return BlockCode.API_CONSECUTIVE_FAILURE.value, RiskRule.API_FAILURES
    if not request.trading_day or not _within_order_window(request):
        return BlockCode.MARKET_CLOSED.value, None
    if not request.account.reconciled:
        return BlockCode.ACCOUNT_NOT_RECONCILED.value, None
    pause = _pause_rule(request)
    if pause is not None:
        return pause.value, pause
    return None, None


def _seed_state(request: PlanRequest) -> _PlanState:
    quotes = {quote.symbol: quote for quote in request.quotes}
    state = _PlanState()
    state.buy_amount = request.counters.daily_buy_amount
    for position in request.account.positions:
        quote = quotes.get(position.symbol)
        value = position.evaluation_amount if quote is None else quote.price * position.quantity
        state.symbol_value[position.symbol] = value
        state.total_value += value
        sector = None if quote is None else quote.sector
        if sector is None:
            state.unclassified_value += value
        else:
            state.sector_value[sector] = state.sector_value.get(sector, Decimal(0)) + value
    return state


def _buy_caps(request: PlanRequest, state: _PlanState, quote: MarketQuote) -> tuple[_Cap, ...]:
    account = request.account
    limits = request.limits
    nav = account.nav
    caps = [
        _Cap(
            RiskRule.SYMBOL_EXPOSURE,
            nav * limits.symbol_exposure,
            state.symbol_value.get(quote.symbol, Decimal(0)),
            nav * limits.symbol_exposure - state.symbol_value.get(quote.symbol, Decimal(0)),
        ),
        _Cap(
            RiskRule.TOTAL_EXPOSURE,
            nav * limits.total_exposure,
            state.total_value,
            nav * limits.total_exposure - state.total_value,
        ),
        _Cap(
            RiskRule.MIN_CASH,
            nav * limits.min_cash,
            account.cash_balance - state.spend,
            account.cash_balance - state.spend - nav * limits.min_cash,
            decreasing=True,
        ),
        _Cap(
            RiskRule.ORDERABLE_CASH,
            account.orderable_cash,
            state.spend,
            account.orderable_cash - state.spend,
        ),
        _Cap(
            RiskRule.DAILY_BUY_AMOUNT,
            account.session_open_nav * limits.daily_buy_amount,
            state.buy_amount,
            account.session_open_nav * limits.daily_buy_amount - state.buy_amount,
        ),
    ]
    if quote.sector is None:
        caps.append(
            _Cap(
                RiskRule.UNCLASSIFIED_EXPOSURE,
                nav * limits.unclassified_exposure,
                state.unclassified_value,
                nav * limits.unclassified_exposure - state.unclassified_value,
            )
        )
    else:
        sector_value = state.sector_value.get(quote.sector, Decimal(0))
        caps.append(
            _Cap(
                RiskRule.SECTOR_EXPOSURE,
                nav * limits.sector_exposure,
                sector_value,
                nav * limits.sector_exposure - sector_value,
            )
        )
    return tuple(caps)


def _order_decisions(
    request: PlanRequest,
    state: _PlanState,
    caps: tuple[_Cap, ...],
    order: tuple[Decimal, Decimal, Decimal],
) -> tuple[RiskDecision, ...]:
    order_value, limit_price, reference_price = order
    limits = request.limits
    order_limit = request.account.nav * limits.order_amount
    open_orders = request.counters.open_orders + state.created + 1
    band_limit = reference_price * (1 + limits.price_band)
    return (
        *(cap.decision(order_value) for cap in caps),
        RiskDecision(RiskRule.ORDER_AMOUNT, order_limit, order_value, order_value <= order_limit),
        RiskDecision(
            RiskRule.OPEN_ORDERS,
            Decimal(limits.open_orders),
            Decimal(open_orders),
            open_orders <= limits.open_orders,
        ),
        RiskDecision(
            RiskRule.ORDER_PRICE_BAND,
            band_limit,
            limit_price,
            within_price_band(OrderSide.BUY, limit_price, reference_price),
        ),
    )


def _rejected(
    state: _PlanState,
    candidate: SignalCandidate,
    quote: MarketQuote | None,
    reject_code: str,
    decisions: tuple[RiskDecision, ...] = (),
) -> PlannedOrder:
    limit_price = None if quote is None else round_to_tick(quote.price, quote.product_type)
    return PlannedOrder(
        sequence=state.next_sequence(),
        symbol=candidate.symbol,
        side=candidate.side,
        quantity=0,
        limit_price=limit_price,
        reference_price=None if quote is None else quote.price,
        reference_received_at=None if quote is None else quote.received_at,
        reject_code=reject_code,
        decisions=decisions,
    )


def _apply_buy(state: _PlanState, quote: MarketQuote, order_value: Decimal) -> None:
    state.symbol_value[quote.symbol] = (
        state.symbol_value.get(quote.symbol, Decimal(0)) + order_value
    )
    state.total_value += order_value
    state.spend += order_value
    state.buy_amount += order_value
    if quote.sector is None:
        state.unclassified_value += order_value
    else:
        state.sector_value[quote.sector] = (
            state.sector_value.get(quote.sector, Decimal(0)) + order_value
        )
    state.created += 1


def _plan_buy(
    request: PlanRequest,
    state: _PlanState,
    candidate: SignalCandidate,
    quote: MarketQuote,
) -> tuple[PlannedOrder, ...]:
    limits = request.limits
    account = request.account
    limit_price = round_to_tick(quote.price, quote.product_type)
    held = next(
        (item for item in account.positions if item.symbol == candidate.symbol),
        None,
    )
    held_quantity = 0 if held is None else held.quantity
    target_value = account.nav * limits.symbol_exposure
    remaining_value = target_value - limit_price * held_quantity
    per_order_quantity = int(account.nav * limits.order_amount / limit_price)
    orders: list[PlannedOrder] = []
    while remaining_value > 0:
        caps = _buy_caps(request, state, quote)
        binding = min(caps, key=lambda cap: cap.available)
        allowed = min(remaining_value, binding.available)
        quantity = min(int(allowed / limit_price), per_order_quantity) if allowed > 0 else 0
        if quantity <= 0:
            if not orders:
                rule = RiskRule.ORDER_AMOUNT if per_order_quantity == 0 else binding.rule
                orders.append(
                    _rejected(
                        state,
                        candidate,
                        quote,
                        rule.value,
                        _order_decisions(
                            request, state, caps, (limit_price, limit_price, quote.price)
                        ),
                    )
                )
            break
        if request.counters.open_orders + state.created >= limits.open_orders:
            if not orders:
                orders.append(
                    _rejected(
                        state,
                        candidate,
                        quote,
                        RiskRule.OPEN_ORDERS.value,
                        _order_decisions(
                            request, state, caps, (limit_price, limit_price, quote.price)
                        ),
                    )
                )
            break
        order_value = limit_price * quantity
        decisions = _order_decisions(request, state, caps, (order_value, limit_price, quote.price))
        orders.append(
            PlannedOrder(
                sequence=state.next_sequence(),
                symbol=candidate.symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                limit_price=limit_price,
                reference_price=quote.price,
                reference_received_at=quote.received_at,
                reject_code=None,
                decisions=decisions,
            )
        )
        _apply_buy(state, quote, order_value)
        remaining_value -= order_value
    return tuple(orders)


def _sell_decisions(
    request: PlanRequest,
    state: _PlanState,
    sellable: int,
    order: tuple[int, int, Decimal, Decimal],
) -> tuple[RiskDecision, ...]:
    quantity, sold, limit_price_value, reference_price = order
    limits = request.limits
    order_value = limit_price_value * quantity
    order_limit = request.account.nav * limits.order_amount
    open_orders = request.counters.open_orders + state.created + 1
    band_limit = reference_price * (1 - limits.price_band)
    return (
        RiskDecision(
            RiskRule.ORDERABLE_QUANTITY,
            Decimal(sellable),
            Decimal(sold + quantity),
            sold + quantity <= sellable,
        ),
        RiskDecision(RiskRule.ORDER_AMOUNT, order_limit, order_value, order_value <= order_limit),
        RiskDecision(
            RiskRule.OPEN_ORDERS,
            Decimal(limits.open_orders),
            Decimal(open_orders),
            open_orders <= limits.open_orders,
        ),
        RiskDecision(
            RiskRule.ORDER_PRICE_BAND,
            band_limit,
            limit_price_value,
            within_price_band(OrderSide.SELL, limit_price_value, reference_price),
        ),
    )


def _plan_sell(
    request: PlanRequest,
    state: _PlanState,
    candidate: SignalCandidate,
    quote: MarketQuote,
) -> tuple[PlannedOrder, ...]:
    limits = request.limits
    held = next(
        (item for item in request.account.positions if item.symbol == candidate.symbol),
        None,
    )
    if held is None or held.quantity == 0:
        return ()
    limit_price = round_to_tick(quote.price, quote.product_type)
    sellable = min(held.quantity, held.orderable_quantity)
    per_order_quantity = int(request.account.nav * limits.order_amount / limit_price)
    if sellable == 0 or per_order_quantity == 0:
        rule = RiskRule.ORDERABLE_QUANTITY if sellable == 0 else RiskRule.ORDER_AMOUNT
        decisions = _sell_decisions(request, state, sellable, (0, 0, limit_price, quote.price))
        return (_rejected(state, candidate, quote, rule.value, decisions),)
    orders: list[PlannedOrder] = []
    sold = 0
    while sold < sellable:
        if request.counters.open_orders + state.created >= limits.open_orders:
            if not orders:
                orders.append(
                    _rejected(
                        state,
                        candidate,
                        quote,
                        RiskRule.OPEN_ORDERS.value,
                        _sell_decisions(
                            request, state, sellable, (0, sold, limit_price, quote.price)
                        ),
                    )
                )
            break
        quantity = min(sellable - sold, per_order_quantity)
        decisions = _sell_decisions(
            request, state, sellable, (quantity, sold, limit_price, quote.price)
        )
        orders.append(
            PlannedOrder(
                sequence=state.next_sequence(),
                symbol=candidate.symbol,
                side=OrderSide.SELL,
                quantity=quantity,
                limit_price=limit_price,
                reference_price=quote.price,
                reference_received_at=quote.received_at,
                reject_code=None,
                decisions=decisions,
            )
        )
        state.created += 1
        sold += quantity
    return tuple(orders)


def _candidate_orders(
    request: PlanRequest,
    state: _PlanState,
    candidate: SignalCandidate,
    quote: MarketQuote | None,
) -> tuple[PlannedOrder, ...]:
    if quote is None:
        return (_rejected(state, candidate, None, BlockCode.DATA_STALE.value),)
    age = request.now - quote.received_at
    if age > timedelta(seconds=request.limits.quote_max_age_seconds):
        return (_rejected(state, candidate, quote, BlockCode.DATA_STALE.value),)
    if quote.trading_status != _ACTIVE_TRADING_STATUS:
        return (_rejected(state, candidate, quote, BlockCode.SYMBOL_SUSPENDED.value),)
    limit_price = round_to_tick(quote.price, quote.product_type)
    if not within_price_band(candidate.side, limit_price, quote.price):
        return (_rejected(state, candidate, quote, RiskRule.ORDER_PRICE_BAND.value),)
    if candidate.side is OrderSide.BUY:
        return _plan_buy(request, state, candidate, quote)
    return _plan_sell(request, state, candidate, quote)


def evaluate_plan(request: PlanRequest) -> RiskEvaluation:
    block_code, pause_rule = _gate(request)
    if block_code is not None:
        return RiskEvaluation(orders=(), block_code=block_code, pause_rule=pause_rule)
    quotes = {quote.symbol: quote for quote in request.quotes}
    state = _seed_state(request)
    orders: list[PlannedOrder] = []
    for candidate in request.candidates:
        orders.extend(_candidate_orders(request, state, candidate, quotes.get(candidate.symbol)))
    return RiskEvaluation(orders=tuple(orders), block_code=None, pause_rule=None)
