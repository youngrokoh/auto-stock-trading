import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final

import anyio

from auto_stock_trading.adapters.brokers.kis_account import KisAccountAdapter
from auto_stock_trading.adapters.brokers.kis_coordination import kis_coordination_scope
from auto_stock_trading.adapters.brokers.kis_coordination_valkey import (
    ValkeyKisRequestCoordinator,
)
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisHttpClient,
    create_kis_http_client,
)
from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
from auto_stock_trading.adapters.database.live_signal_store import (
    PostgresLiveSignalStore,
    StoredSignal,
)
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_stock_store import PostgresStockStore
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.planning import (
    AutomationTransition,
    OrderPlanner,
    PlanInput,
)
from auto_stock_trading.application.trading.signals import STRATEGY_NAME
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide
from auto_stock_trading.domain.risk.engine import SignalCandidate
from auto_stock_trading.domain.risk.limits import seoul_trading_date
from auto_stock_trading.domain.strategies.live_signal import signal_candidates
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import (
    load_kis_account,
    load_kis_credentials,
)

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.account import AccountSnapshotObservation
    from auto_stock_trading.domain.orders.records import OrderPlanRecord


@final
class MissingAccountSource:
    """계좌 secret이 없을 때 계좌 조회 없는 차단 경로만 허용하는 fail-closed 소스."""

    def __init__(self, error: KisConfigurationError) -> None:
        self._error = error

    async def fetch_balance(self) -> AccountSnapshotObservation:
        raise self._error

    async def close(self) -> None:
        return None


_STRATEGY_NAME: Final = "ma-rsi"
_STRATEGY_VERSION: Final = "1"
# 기본 전략 신원. 신호로 계획할 때는 신호가 가진 신원을 그대로 쓴다(계보가 갈라지면 안 된다).
_MA_RSI_STRATEGY: Final = (_STRATEGY_NAME, _STRATEGY_VERSION)
_NO_OFFSET: Final = Decimal(0)
_MANUAL_REASON: Final = "USER_COMMAND"
_PERCENT: Final = Decimal(100)


class Arguments(argparse.Namespace):
    symbol: str = "005930"
    side: str = OrderSide.BUY.value
    signal_date: str | None = None
    parameters: str = '{"long_period":20,"rsi_overbought":"70","rsi_period":14,"short_period":5}'
    automation: str | None = None
    account_snapshot: bool = False
    from_signal: bool = False
    price_offset_pct: str | None = None


def _http_client(settings: Settings) -> KisHttpClient:
    credentials = load_kis_credentials(settings)
    return KisHttpClient(
        create_kis_http_client(settings.kis_base_url),
        credentials,
        ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(),
            kis_coordination_scope(
                settings.kis_environment.value,
                credentials.app_key,
                credentials.app_secret,
            ),
        ),
    )


async def set_automation_state(state_text: str) -> str:
    """자동매매 상태를 사람이 명시적으로 전이한다. 실전 환경에서는 거부한다."""
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        message = "automation state changes are allowed in the paper environment only"
        raise RuntimeError(message)
    store = PostgresTradingStore.from_url(settings.database_url.get_secret_value())
    now = datetime.now(UTC)
    try:
        record = await store.transition_automation(
            AutomationTransition(
                environment=settings.kis_environment.value,
                requested=AutomationState(state_text),
                reason_code=_MANUAL_REASON,
                occurred_at=now,
                trading_date=seoul_trading_date(now),
            )
        )
    finally:
        await store.close()
    return record.state.value


async def collect_account_snapshot() -> str:
    """모의 계좌 잔고를 조회해 append-only 스냅샷으로 저장한다. 주문은 만들지 않는다."""
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        message = "account snapshots are collected in the paper environment only"
        raise RuntimeError(message)
    store = PostgresTradingStore.from_url(settings.database_url.get_secret_value())
    accounts = KisAccountAdapter(_http_client(settings), load_kis_account(settings), paper=True)
    try:
        observation = await accounts.fetch_balance()
        stored = await store.save_account_snapshot(observation)
    finally:
        await accounts.close()
        await store.close()
    snapshot = stored.snapshot
    holdings = ",".join(f"{position.symbol}:{position.quantity}" for position in snapshot.positions)
    return (
        f"snapshot_id={stored.snapshot_id} account={snapshot.account_reference} "
        f"nav={snapshot.nav} cash={snapshot.cash_balance} "
        f"orderable_cash={snapshot.orderable_cash} positions={snapshot.position_value} "
        f"broker_net_asset={snapshot.broker_net_asset} holdings={holdings or '-'}"
    )


async def _signal_candidates(
    settings: Settings,
) -> tuple[tuple[SignalCandidate, ...], StoredSignal | None]:
    """저장된 신호와 **방금 조회한 보유**의 차집합으로 후보를 만든다(ADR-0016 결정 4).

    보유를 저장된 스냅샷에서 읽으면 그 사이 체결이 반영되지 않아 이미 보유한 종목을 다시 살 수 있다.
    그래서 계좌를 새로 조회한다.
    """
    database_url = settings.database_url.get_secret_value()
    signals = PostgresLiveSignalStore.from_url(database_url)
    accounts = KisAccountAdapter(_http_client(settings), load_kis_account(settings), paper=True)
    try:
        latest = await signals.latest_targets(settings.kis_environment.value, STRATEGY_NAME)
        if latest is None:
            return (), None
        observation = await accounts.fetch_balance()
    finally:
        await accounts.close()
        await signals.close()
    holdings = tuple(
        position.symbol for position in observation.snapshot.positions if position.quantity > 0
    )
    return signal_candidates(latest.targets, holdings), latest


def _signal_note(signal: StoredSignal, candidates: int) -> str:
    return (
        f"basis_date={signal.basis_date} rebalance_date={signal.rebalance_date} "
        f"candidates={candidates}"
    )


@dataclass(frozen=True, slots=True)
class SignalPlanOutcome:
    """신호 기반 계획의 결과. 예약 작업과 CLI가 같은 값을 본다."""

    plan: OrderPlanRecord | None
    signal: StoredSignal | None
    candidates: int
    note: str


async def plan_from_signal_record() -> SignalPlanOutcome:
    """저장된 신호를 후보로 바꿔 계획한다. 신호를 여기서 계산하지 않는다."""
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        message = "order planning is allowed in the paper environment only"
        raise RuntimeError(message)
    candidates, signal = await _signal_candidates(settings)
    if signal is None:
        return SignalPlanOutcome(plan=None, signal=None, candidates=0, note="no_signal")
    if not candidates:
        return SignalPlanOutcome(
            plan=None,
            signal=signal,
            candidates=0,
            note=f"no_candidate basis_date={signal.basis_date} targets={len(signal.targets)}",
        )
    note = _signal_note(signal, len(candidates))
    plan = await _plan_candidates(
        settings,
        candidates,
        signal.parameters_json,
        strategy=(signal.strategy_name, signal.strategy_version),
    )
    return SignalPlanOutcome(
        plan=plan,
        signal=signal,
        candidates=len(candidates),
        note=note,
    )


async def plan_from_signal() -> str:
    outcome = await plan_from_signal_record()
    if outcome.plan is None:
        return outcome.note
    return format_plan(outcome.plan, outcome.note)


async def _plan_candidates(  # noqa: PLR0913 — 계획 입력을 그대로 노출한다
    settings: Settings,
    candidates: tuple[SignalCandidate, ...],
    parameters_json: str,
    *,
    price_offset: Decimal = _NO_OFFSET,
    signal_date: date | None = None,
    strategy: tuple[str, str] = _MA_RSI_STRATEGY,
) -> OrderPlanRecord:
    """후보를 받아 계획한다. 후보를 어디서 얻었는지는 호출자가 정한다.

    문자열이 아니라 기록을 돌려준다 — 예약 작업이 결과를 문자열로 파싱하게 두면 안 된다.
    """
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    market_data = PostgresMarketDataRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
    sectors = PostgresStockStore.from_url(database_url)
    quotes = KisMarketDataAdapter(_http_client(settings), instrument_details_available=False)
    accounts: KisAccountAdapter | MissingAccountSource
    try:
        account = load_kis_account(settings)
    except KisConfigurationError as error:
        accounts = MissingAccountSource(error)
    else:
        accounts = KisAccountAdapter(_http_client(settings), account, paper=True)
    planner = OrderPlanner(
        calendar=calendar,
        instruments=market_data,
        quotes=quotes,
        accounts=accounts,
        store=store,
        sectors=sectors,
    )
    now = datetime.now(UTC)
    request = PlanInput(
        environment=settings.kis_environment.value,
        strategy_name=strategy[0],
        strategy_version=strategy[1],
        parameters_json=parameters_json,
        signal_date=signal_date if signal_date is not None else seoul_trading_date(now),
        candidates=candidates,
        price_offset=price_offset,
    )
    try:
        plan = await planner.plan(request, now)
    finally:
        await quotes.close()
        await accounts.close()
        await calendar.close()
        await market_data.close()
        await sectors.close()
        await store.close()
    return plan


def format_plan(plan: OrderPlanRecord, note: str) -> str:
    if plan.status == "blocked":
        return f"blocked plan_id={plan.plan_id} block_code={plan.block_code} {note}".rstrip()
    evaluated = sum(1 for order in plan.orders if order.reject_code is None)
    rejected = tuple(order.reject_code for order in plan.orders if order.reject_code is not None)
    stored = plan.stored_orders if plan.stored_orders is not None else 0
    skipped = max(len(plan.orders) - stored, 0)
    return (
        f"created plan_id={plan.plan_id} stored={stored} evaluated={evaluated} "
        f"duplicates={skipped} rejected={len(rejected)} "
        f"reasons={','.join(rejected) or '-'} nav={plan.nav_basis} {note}"
    ).rstrip()


async def plan_orders(arguments: Arguments) -> str:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        message = "order planning is allowed in the paper environment only"
        raise RuntimeError(message)
    plan = await _plan_candidates(
        settings,
        (SignalCandidate(arguments.symbol, OrderSide(arguments.side)),),
        arguments.parameters,
        price_offset=(
            Decimal(0)
            if arguments.price_offset_pct is None
            else Decimal(arguments.price_offset_pct) / _PERCENT
        ),
        signal_date=(
            date.fromisoformat(arguments.signal_date) if arguments.signal_date is not None else None
        ),
    )
    return format_plan(plan, "")


def main() -> None:
    parser = argparse.ArgumentParser(description="모의투자 주문 계획 생성 (주문 제출은 하지 않음)")
    _ = parser.add_argument("--symbol", default=Arguments.symbol)
    _ = parser.add_argument("--side", choices=(OrderSide.BUY.value, OrderSide.SELL.value))
    _ = parser.add_argument("--signal-date")
    _ = parser.add_argument("--parameters", default=Arguments.parameters)
    _ = parser.add_argument(
        "--automation",
        choices=tuple(state.value for state in AutomationState),
    )
    _ = parser.add_argument("--account-snapshot", action="store_true")
    _ = parser.add_argument("--from-signal", action="store_true")
    _ = parser.add_argument("--price-offset-pct")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.from_signal:
        print(anyio.run(plan_from_signal))  # noqa: T201
        return
    if arguments.account_snapshot:
        print(anyio.run(collect_account_snapshot))  # noqa: T201
        return
    if arguments.automation is not None:
        print(anyio.run(set_automation_state, arguments.automation))  # noqa: T201
        return
    print(anyio.run(plan_orders, arguments))  # noqa: T201


if __name__ == "__main__":
    main()
