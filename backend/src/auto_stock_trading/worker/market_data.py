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
from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.application.market_data import MarketDataCollector
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


def load_kis_credentials(settings: Settings) -> KisCredentials:
    return _load_kis_credentials(settings)


async def collect_seed_market_data(
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> tuple[str, ...]:
    settings = Settings()
    credentials = load_kis_credentials(settings)
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
    instrument_details_available = settings.kis_environment is KisEnvironment.LIVE
    source = KisMarketDataAdapter(
        http_client,
        instrument_details_available=instrument_details_available,
    )
    store = PostgresMarketDataRepository.from_url(settings.database_url.get_secret_value())
    collector = MarketDataCollector(source, store)
    try:
        for target in _TARGETS:
            _ = await collector.collect(target, start_date, end_date, datetime.now(UTC))
    finally:
        await source.close()
        await store.close()
    return tuple(target.symbol for target in _TARGETS)


collect_seed_market_data_task = broker.task(task_name="collect_seed_market_data")(
    collect_seed_market_data
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
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.confirm_calendar_today:
        _ = anyio.run(run_claimed_kis_market_calendar_confirmation)
    elif arguments.calendar_year is not None:
        _ = anyio.run(run_claimed_krx_market_calendar, arguments.calendar_year)
    else:
        _ = anyio.run(collect_seed_market_data, arguments.start_date, arguments.end_date)


if __name__ == "__main__":
    main()
