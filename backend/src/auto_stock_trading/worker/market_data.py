import argparse
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import anyio
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--start-date")
    _ = parser.add_argument("--end-date")
    arguments = parser.parse_args(namespace=Arguments())
    _ = anyio.run(collect_seed_market_data, arguments.start_date, arguments.end_date)


if __name__ == "__main__":
    main()
