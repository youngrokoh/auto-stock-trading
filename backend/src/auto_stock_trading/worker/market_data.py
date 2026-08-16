import argparse
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import anyio
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_coordination import (
    ValkeyKisRequestCoordinator,
    kis_coordination_scope,
)
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisCredentials,
    KisHttpClient,
    create_kis_http_client,
)
from auto_stock_trading.adapters.brokers.kis_market_calendar import (
    KisMarketCalendarVerifier,
)
from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.exchanges.krx_market_calendar import (
    KrxHttpClient,
    KrxMarketCalendarAdapter,
    create_krx_http_client,
)
from auto_stock_trading.application.market_calendar import (
    KisCalendarConfirmer,
    KrxCalendarCollector,
)
from auto_stock_trading.application.market_data import MarketDataCollector
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarSessionRange,
    MarketSessionType,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.broker import broker

if TYPE_CHECKING:
    from pathlib import Path

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
    return KisCredentials(
        _secret_from(settings.kis_app_key, settings.kis_app_key_file, "AUTO_STOCK_KIS_APP_KEY"),
        _secret_from(
            settings.kis_app_secret,
            settings.kis_app_secret_file,
            "AUTO_STOCK_KIS_APP_SECRET",
        ),
    )


def _secret_from(direct: SecretStr | None, file_path: Path | None, setting_name: str) -> SecretStr:
    if direct is not None and direct.get_secret_value():
        return direct
    if file_path is not None:
        try:
            value = file_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            message = f"{setting_name} or {setting_name}_FILE is required"
            raise KisConfigurationError(message) from error
        if value:
            return SecretStr(value)
    message = f"{setting_name} or {setting_name}_FILE is required"
    raise KisConfigurationError(message)


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
    settings = Settings()
    selected_year = year if year is not None else datetime.now(_SEOUL).year
    query = CalendarSessionRange(
        "KR",
        "XKRX",
        date(selected_year, 1, 1),
        date(selected_year, 12, 31),
    )
    source = KrxMarketCalendarAdapter(KrxHttpClient(create_krx_http_client(settings.krx_base_url)))
    store = PostgresMarketCalendarRepository.from_url(settings.database_url.get_secret_value())
    collector = KrxCalendarCollector(source, store)
    try:
        records = await collector.collect(query, datetime.now(UTC))
    finally:
        await source.close()
        await store.close()
    return len(records)


collect_krx_market_calendar_task = broker.task(task_name="collect_krx_market_calendar")(
    collect_krx_market_calendar
)


async def confirm_today_market_calendar() -> str:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.LIVE:
        message = "KIS market calendar confirmation requires the live environment"
        raise KisConfigurationError(message)
    credentials = load_kis_credentials(settings)
    trading_date = datetime.now(_SEOUL).date()
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
    verifier = KisMarketCalendarVerifier(http_client)
    store = PostgresMarketCalendarRepository.from_url(settings.database_url.get_secret_value())
    confirmer = KisCalendarConfirmer(verifier, store)
    key = CalendarSessionKey("KR", "XKRX", trading_date, MarketSessionType.REGULAR)
    try:
        _record = await confirmer.confirm(key, datetime.now(UTC))
    finally:
        await verifier.close()
        await store.close()
    return trading_date.isoformat()


confirm_today_market_calendar_task = broker.task(task_name="confirm_today_market_calendar")(
    confirm_today_market_calendar
)


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--start-date")
    _ = parser.add_argument("--end-date")
    _ = parser.add_argument("--calendar-year", type=int)
    _ = parser.add_argument("--confirm-calendar-today", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.confirm_calendar_today:
        _ = anyio.run(confirm_today_market_calendar)
    elif arguments.calendar_year is not None:
        _ = anyio.run(collect_krx_market_calendar, arguments.calendar_year)
    else:
        _ = anyio.run(collect_seed_market_data, arguments.start_date, arguments.end_date)


if __name__ == "__main__":
    main()
