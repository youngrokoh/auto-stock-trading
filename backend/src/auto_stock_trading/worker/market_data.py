import argparse
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import anyio

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
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker.broker import broker

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_TARGETS: Final = (
    InstrumentTarget("005930", ProductType.STOCK),
    InstrumentTarget("069500", ProductType.ETF),
)


class Arguments(argparse.Namespace):
    start_date: str | None = None
    end_date: str | None = None


async def collect_seed_market_data(
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> tuple[str, ...]:
    settings = Settings()
    app_key = settings.kis_app_key
    app_secret = settings.kis_app_secret
    if app_key is None or app_secret is None:
        message = "AUTO_STOCK_KIS_APP_KEY and AUTO_STOCK_KIS_APP_SECRET are required"
        raise KisConfigurationError(message)
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
        KisCredentials(app_key, app_secret),
    )
    source = KisMarketDataAdapter(http_client)
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
