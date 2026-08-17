import argparse
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import anyio
from pydantic import SecretStr

from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    PostgresCorporateActionStore,
)
from auto_stock_trading.adapters.disclosures.kodex_distributions import (
    KodexDistributionAdapter,
    KodexDistributionTarget,
    create_kodex_http_client,
)
from auto_stock_trading.adapters.disclosures.opendart_corporate_actions import (
    DartCorporateActionAdapter,
    DartDividendTarget,
)
from auto_stock_trading.adapters.disclosures.opendart_http import (
    DartConfigurationError,
    DartHttpClient,
    create_dart_http_client,
)
from auto_stock_trading.application.corporate_actions import (
    CorporateActionCollector,
    CorporateActionSource,
)
from auto_stock_trading.settings.runtime import Settings

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_DEFAULT_TARGET: Final = DartDividendTarget(symbol="005930", corp_code="00126380")
_DEFAULT_ETF_TARGET: Final = KodexDistributionTarget(symbol="069500", fund_id="2ETF01")
_DEFAULT_RANGE_DAYS: Final = 365


class Arguments(argparse.Namespace):
    symbol: str | None = None
    corp_code: str = _DEFAULT_TARGET.corp_code
    fund_id: str = _DEFAULT_ETF_TARGET.fund_id
    etf_distributions: bool = False
    start_date: str | None = None
    end_date: str | None = None


def load_dart_api_key(settings: Settings) -> SecretStr:
    if settings.dart_api_key is not None and settings.dart_api_key.get_secret_value():
        return settings.dart_api_key
    message = "AUTO_STOCK_DART_API_KEY or AUTO_STOCK_DART_API_KEY_FILE is required"
    if settings.dart_api_key_file is not None:
        try:
            value = settings.dart_api_key_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as error:
            raise DartConfigurationError(message) from error
        if value:
            return SecretStr(value)
    raise DartConfigurationError(message)


def _collection_range(
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
        else end_date - timedelta(days=_DEFAULT_RANGE_DAYS)
    )
    return start_date, end_date


async def _collect(
    source: CorporateActionSource,
    settings: Settings,
    window: tuple[date, date],
) -> int:
    store = PostgresCorporateActionStore.from_url(settings.database_url.get_secret_value())
    collector = CorporateActionCollector(source, store)
    try:
        bundle = await collector.collect(window[0], window[1], datetime.now(UTC))
    finally:
        await source.close()
        await store.close()
    return len(bundle.observations)


async def collect_dart_cash_dividends(
    symbol: str = _DEFAULT_TARGET.symbol,
    corp_code: str = _DEFAULT_TARGET.corp_code,
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> int:
    settings = Settings()
    api_key = load_dart_api_key(settings)
    source = DartCorporateActionAdapter(
        DartHttpClient(create_dart_http_client(settings.dart_base_url), api_key),
        DartDividendTarget(symbol=symbol, corp_code=corp_code),
    )
    return await _collect(source, settings, _collection_range(start_date_text, end_date_text))


async def collect_kodex_distributions(
    symbol: str = _DEFAULT_ETF_TARGET.symbol,
    fund_id: str = _DEFAULT_ETF_TARGET.fund_id,
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> int:
    settings = Settings()
    source = KodexDistributionAdapter(
        create_kodex_http_client(settings.kodex_base_url),
        KodexDistributionTarget(symbol=symbol, fund_id=fund_id),
    )
    return await _collect(source, settings, _collection_range(start_date_text, end_date_text))


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--symbol")
    _ = parser.add_argument("--corp-code", default=_DEFAULT_TARGET.corp_code)
    _ = parser.add_argument("--fund-id", default=_DEFAULT_ETF_TARGET.fund_id)
    _ = parser.add_argument("--etf-distributions", action="store_true")
    _ = parser.add_argument("--start-date")
    _ = parser.add_argument("--end-date")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.etf_distributions:
        _ = anyio.run(
            collect_kodex_distributions,
            arguments.symbol or _DEFAULT_ETF_TARGET.symbol,
            arguments.fund_id,
            arguments.start_date,
            arguments.end_date,
        )
    else:
        _ = anyio.run(
            collect_dart_cash_dividends,
            arguments.symbol or _DEFAULT_TARGET.symbol,
            arguments.corp_code,
            arguments.start_date,
            arguments.end_date,
        )


if __name__ == "__main__":
    main()
