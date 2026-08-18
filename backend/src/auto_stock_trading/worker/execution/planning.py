import argparse
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final, final

import anyio

from auto_stock_trading.adapters.brokers.kis_account import KisAccountAdapter
from auto_stock_trading.adapters.brokers.kis_coordination import (
    ValkeyKisRequestCoordinator,
    kis_coordination_scope,
)
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisHttpClient,
    create_kis_http_client,
)
from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.planning import (
    AutomationTransition,
    OrderPlanner,
    PlanInput,
)
from auto_stock_trading.domain.orders.models import AutomationState, OrderSide
from auto_stock_trading.domain.risk.engine import SignalCandidate
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import (
    load_kis_account,
    load_kis_credentials,
)

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.account import AccountSnapshotObservation


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
_MANUAL_REASON: Final = "USER_COMMAND"


class Arguments(argparse.Namespace):
    symbol: str = "005930"
    side: str = OrderSide.BUY.value
    signal_date: str | None = None
    parameters: str = '{"long_period":20,"rsi_overbought":"70","rsi_period":14,"short_period":5}'
    automation: str | None = None


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
                trading_date=now.date(),
            )
        )
    finally:
        await store.close()
    return record.state.value


async def plan_orders(arguments: Arguments) -> str:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        message = "order planning is allowed in the paper environment only"
        raise RuntimeError(message)
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    market_data = PostgresMarketDataRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
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
    )
    now = datetime.now(UTC)
    request = PlanInput(
        environment=settings.kis_environment.value,
        strategy_name=_STRATEGY_NAME,
        strategy_version=_STRATEGY_VERSION,
        parameters_json=arguments.parameters,
        signal_date=(
            date.fromisoformat(arguments.signal_date)
            if arguments.signal_date is not None
            else now.date()
        ),
        candidates=(SignalCandidate(arguments.symbol, OrderSide(arguments.side)),),
    )
    try:
        plan = await planner.plan(request, now)
    finally:
        await quotes.close()
        await accounts.close()
        await calendar.close()
        await market_data.close()
        await store.close()
    if plan.status == "blocked":
        return f"blocked plan_id={plan.plan_id} block_code={plan.block_code}"
    planned = sum(1 for order in plan.orders if order.reject_code is None)
    rejected = tuple(order.reject_code for order in plan.orders if order.reject_code is not None)
    return (
        f"created plan_id={plan.plan_id} planned={planned} "
        f"rejected={len(rejected)} reasons={','.join(rejected) or '-'} "
        f"nav={plan.nav_basis}"
    )


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
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.automation is not None:
        print(anyio.run(set_automation_state, arguments.automation))  # noqa: T201
        return
    print(anyio.run(plan_orders, arguments))  # noqa: T201


if __name__ == "__main__":
    main()
