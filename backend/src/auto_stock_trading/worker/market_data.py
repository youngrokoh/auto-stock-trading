import argparse
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import anyio

from auto_stock_trading.adapters.brokers.kis_coordination import (
    ValkeyKisRequestCoordinator,
    kis_coordination_scope,
)
from auto_stock_trading.adapters.brokers.kis_http import (
    KisCredentials,
    KisHttpClient,
    create_kis_http_client,
)
from auto_stock_trading.adapters.brokers.kis_investor_flows import KisInvestorFlowAdapter
from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
from auto_stock_trading.adapters.brokers.kis_minute_bars import KisMinuteBarAdapter
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_investor_flow_store import (
    PostgresInvestorFlowStore,
)
from auto_stock_trading.adapters.database.market_data_minute_bar_store import (
    PostgresMinuteBarStore,
)
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.application.investor_flows import InvestorFlowCollector
from auto_stock_trading.application.market_data import DailyBarConfirmer, MarketDataCollector
from auto_stock_trading.application.minute_bars import MinuteBarCollector
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker import market_calendar
from auto_stock_trading.worker.broker import broker
from auto_stock_trading.worker.kis_credentials import load_kis_credentials as _load_kis_credentials
from auto_stock_trading.worker.market_calendar_schedule import (
    run_claimed_kis_market_calendar_confirmation,
    run_claimed_krx_market_calendar,
)

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TARGETS: Final = (
    InstrumentTarget("005930", ProductType.STOCK),
    InstrumentTarget("069500", ProductType.ETF),
)


class Arguments(argparse.Namespace):
    start_date: str | None = None
    end_date: str | None = None
    calendar_year: int | None = None
    confirm_calendar_today: bool = False
    confirm_daily_bars: bool = False
    collect_minute_bars: bool = False
    collect_investor_flows: bool = False


def load_kis_credentials(settings: Settings) -> KisCredentials:
    return _load_kis_credentials(settings)


def _seed_collection_range(
    start_date_text: str | None,
    end_date_text: str | None,
) -> tuple[date, date]:
    end_date = (
        date.fromisoformat(end_date_text)
        if end_date_text is not None
        else datetime.now(_SEOUL).date()
    )
    start_date = (
        date.fromisoformat(start_date_text)
        if start_date_text is not None
        else end_date - timedelta(days=30)
    )
    return start_date, end_date


def _seed_source_and_store(
    settings: Settings,
) -> tuple[KisMarketDataAdapter, PostgresMarketDataRepository]:
    credentials = load_kis_credentials(settings)
    http_client = KisHttpClient(
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
    source = KisMarketDataAdapter(
        http_client,
        instrument_details_available=settings.kis_environment is KisEnvironment.LIVE,
    )
    store = PostgresMarketDataRepository.from_url(settings.database_url.get_secret_value())
    return source, store


async def collect_seed_market_data(
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> tuple[str, ...]:
    settings = Settings()
    start_date, end_date = _seed_collection_range(start_date_text, end_date_text)
    source, store = _seed_source_and_store(settings)
    collector = MarketDataCollector(source, store)
    try:
        for target in _TARGETS:
            _ = await collector.collect(target, start_date, end_date, datetime.now(UTC))
    finally:
        await source.close()
        await store.close()
    return tuple(target.symbol for target in _TARGETS)


async def confirm_seed_daily_bars(
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> tuple[int, int]:
    settings = Settings()
    start_date, end_date = _seed_collection_range(start_date_text, end_date_text)
    source, store = _seed_source_and_store(settings)
    confirmer = DailyBarConfirmer(source, store)
    confirmed = 0
    pending = 0
    try:
        for target in _TARGETS:
            result = await confirmer.confirm(target, start_date, end_date, datetime.now(UTC))
            confirmed += result.confirmed
            pending += result.pending
    finally:
        await source.close()
        await store.close()
    return confirmed, pending


async def collect_seed_minute_bars() -> tuple[int, int, int]:
    settings = Settings()
    credentials = load_kis_credentials(settings)
    http_client = KisHttpClient(
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
    source = KisMinuteBarAdapter(http_client)
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    store = PostgresMinuteBarStore.from_url(database_url)
    collector = MinuteBarCollector(calendar, source, store)
    collected = 0
    confirmed = 0
    pending = 0
    try:
        for target in _TARGETS:
            result = await collector.collect(target, datetime.now(UTC))
            collected += result.collected
            confirmed += result.confirmed
            pending += result.pending
    finally:
        await source.close()
        await calendar.close()
        await store.close()
    return collected, confirmed, pending


collect_seed_market_data_task = broker.task(task_name="collect_seed_market_data")(
    collect_seed_market_data
)
collect_seed_minute_bars_task = broker.task(task_name="collect_seed_minute_bars")(
    collect_seed_minute_bars
)


async def collect_seed_investor_flows() -> int:
    settings = Settings()
    credentials = load_kis_credentials(settings)
    http_client = KisHttpClient(
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
    source = KisInvestorFlowAdapter(http_client)
    store = PostgresInvestorFlowStore.from_url(settings.database_url.get_secret_value())
    collector = InvestorFlowCollector(source, store)
    collected = 0
    try:
        for target in _TARGETS:
            result = await collector.collect(target, datetime.now(UTC))
            collected += result.collected
    finally:
        await source.close()
        await store.close()
    return collected


collect_seed_investor_flows_task = broker.task(task_name="collect_seed_investor_flows")(
    collect_seed_investor_flows
)


async def collect_krx_market_calendar(year: int | None = None) -> int:
    return await market_calendar.collect_krx_market_calendar(year, Settings())


async def confirm_today_market_calendar() -> str:
    return await market_calendar.confirm_today_market_calendar(Settings())


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--start-date")
    _ = parser.add_argument("--end-date")
    _ = parser.add_argument("--calendar-year", type=int)
    _ = parser.add_argument("--confirm-calendar-today", action="store_true")
    _ = parser.add_argument("--confirm-daily-bars", action="store_true")
    _ = parser.add_argument("--collect-minute-bars", action="store_true")
    _ = parser.add_argument("--collect-investor-flows", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.collect_investor_flows:
        _ = anyio.run(collect_seed_investor_flows)
    elif arguments.collect_minute_bars:
        _ = anyio.run(collect_seed_minute_bars)
    elif arguments.confirm_daily_bars:
        _ = anyio.run(confirm_seed_daily_bars, arguments.start_date, arguments.end_date)
    elif arguments.confirm_calendar_today:
        _ = anyio.run(run_claimed_kis_market_calendar_confirmation)
    elif arguments.calendar_year is not None:
        _ = anyio.run(run_claimed_krx_market_calendar, arguments.calendar_year)
    else:
        _ = anyio.run(collect_seed_market_data, arguments.start_date, arguments.end_date)


if __name__ == "__main__":
    main()
