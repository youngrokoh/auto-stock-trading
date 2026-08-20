import argparse
from datetime import UTC, date, datetime, timedelta
from typing import Final, final
from zoneinfo import ZoneInfo

import anyio
from pydantic import SecretStr

from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_adjustment_store import (
    PostgresAdjustmentStore,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    PostgresCorporateActionStore,
)
from auto_stock_trading.adapters.database.market_data_exdate_store import PostgresExDateStore
from auto_stock_trading.adapters.database.reference_corp_code_store import PostgresCorpCodeStore
from auto_stock_trading.adapters.disclosures.dart_corp_codes import DartCorpCodeAdapter
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
from auto_stock_trading.application.corporate_action_exdates import ExDateResolver
from auto_stock_trading.application.corporate_actions import (
    CorporateActionCollector,
    CorporateActionSource,
    UniverseDividendCollection,
)
from auto_stock_trading.domain.market_data.adjustment_datasets import AdjustmentRequest
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
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
    collect_corp_codes: bool = False
    universe_dividends: bool = False
    universe_ex_dates: bool = False
    confirm_ex_dates: bool = False
    build_adjusted: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    knowledge_cutoff: str | None = None


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


@final
class _UniverseDividendSource:
    """유니버스 배당 수집이 공용 DART 클라이언트와 저장소를 재사용하게 한다."""

    def __init__(self, client: DartHttpClient, store: PostgresCorporateActionStore) -> None:
        self._client = client
        self._store = store

    async def collect_symbol(
        self,
        symbol: str,
        corp_code: str,
        start_date: date,
        end_date: date,
        now: datetime,
    ) -> int:
        adapter = DartCorporateActionAdapter(
            self._client,
            DartDividendTarget(symbol=symbol, corp_code=corp_code),
        )
        bundle = await CorporateActionCollector(adapter, self._store).collect(
            start_date,
            end_date,
            now,
        )
        return len(bundle.observations)


async def collect_dart_corp_codes() -> tuple[int, int]:
    """DART 고유번호 전체 파일을 버전 사실로 적재한다. 점검 중이면 실패한다."""
    settings = Settings()
    api_key = load_dart_api_key(settings)
    source = DartCorpCodeAdapter(
        DartHttpClient(create_dart_http_client(settings.dart_base_url), api_key)
    )
    store = PostgresCorpCodeStore.from_url(settings.database_url.get_secret_value())
    try:
        bundle = await source.fetch_corp_codes(datetime.now(UTC))
        saved = await store.save_corp_codes(bundle)
    finally:
        await source.close()
        await store.close()
    return len(bundle.codes), saved


async def collect_universe_dividends(
    start_date_text: str | None = None,
    end_date_text: str | None = None,
) -> tuple[int, int, int, tuple[str, ...]]:
    settings = Settings()
    api_key = load_dart_api_key(settings)
    start_date, end_date = _collection_range(start_date_text, end_date_text)
    database_url = settings.database_url.get_secret_value()
    client = DartHttpClient(create_dart_http_client(settings.dart_base_url), api_key)
    codes = PostgresCorpCodeStore.from_url(database_url)
    store = PostgresCorporateActionStore.from_url(database_url)
    collection = UniverseDividendCollection(
        codes=codes,
        source=_UniverseDividendSource(client, store),
    )
    try:
        result = await collection.run(start_date, end_date, datetime.now(UTC))
    finally:
        await client.close()
        await codes.close()
        await store.close()
    return result.symbols, result.observations, result.failed, result.missing_corp_codes


async def confirm_universe_ex_dates() -> tuple[int, int, int]:
    """락일이 미확정인 종목만 골라 확정한다. 규칙은 `ExDateResolver`가 그대로 갖는다."""
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    store = PostgresExDateStore.from_url(database_url)
    try:
        symbols = await store.symbols_missing_ex_date()
    finally:
        await store.close()
    resolved, skipped = await confirm_corporate_action_ex_dates(symbols)
    return len(symbols), resolved, skipped


async def confirm_corporate_action_ex_dates(
    symbols: tuple[str, ...] = (_DEFAULT_TARGET.symbol, _DEFAULT_ETF_TARGET.symbol),
) -> tuple[int, int]:
    settings = Settings()
    database_url = settings.database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    store = PostgresExDateStore.from_url(database_url)
    resolver = ExDateResolver(calendar=calendar, store=store)
    resolved = 0
    skipped = 0
    try:
        for symbol in symbols:
            resolution = await resolver.resolve(symbol, datetime.now(UTC))
            resolved += resolution.resolved
            skipped += resolution.skipped
    finally:
        await calendar.close()
        await store.close()
    return resolved, skipped


async def build_adjusted_dataset(
    symbol: str,
    method_text: str,
    range_start_text: str,
    price_cutoff_text: str,
    knowledge_cutoff_text: str | None = None,
) -> str:
    settings = Settings()
    store = PostgresAdjustmentStore.from_url(settings.database_url.get_secret_value())
    request = AdjustmentRequest(
        symbol=symbol,
        method=AdjustmentMethod(method_text),
        range_start=date.fromisoformat(range_start_text),
        price_cutoff_date=date.fromisoformat(price_cutoff_text),
        knowledge_cutoff_at=(
            datetime.fromisoformat(knowledge_cutoff_text)
            if knowledge_cutoff_text is not None
            else datetime.now(UTC)
        ),
    )
    try:
        record = await store.build_dataset(request, datetime.now(UTC))
    finally:
        await store.close()
    return str(record.dataset_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--symbol")
    _ = parser.add_argument("--corp-code", default=_DEFAULT_TARGET.corp_code)
    _ = parser.add_argument("--fund-id", default=_DEFAULT_ETF_TARGET.fund_id)
    _ = parser.add_argument("--etf-distributions", action="store_true")
    _ = parser.add_argument("--confirm-ex-dates", action="store_true")
    _ = parser.add_argument(
        "--build-adjusted",
        choices=("split_adjusted", "total_return"),
    )
    _ = parser.add_argument("--start-date")
    _ = parser.add_argument("--end-date")
    _ = parser.add_argument("--knowledge-cutoff")
    _ = parser.add_argument("--collect-corp-codes", action="store_true")
    _ = parser.add_argument("--universe-dividends", action="store_true")
    _ = parser.add_argument("--universe-ex-dates", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.confirm_ex_dates:
        _ = anyio.run(
            confirm_corporate_action_ex_dates,
            (_DEFAULT_TARGET.symbol, _DEFAULT_ETF_TARGET.symbol)
            if arguments.symbol is None
            else (arguments.symbol,),
        )
    elif arguments.build_adjusted is not None:
        if arguments.symbol is None or arguments.start_date is None or arguments.end_date is None:
            parser.error("--build-adjusted requires --symbol, --start-date and --end-date")
        _ = anyio.run(
            build_adjusted_dataset,
            arguments.symbol,
            arguments.build_adjusted,
            arguments.start_date,
            arguments.end_date,
            arguments.knowledge_cutoff,
        )
    elif arguments.universe_ex_dates:
        symbols, resolved, skipped = anyio.run(confirm_universe_ex_dates)
        print(f"ex_dates symbols={symbols} resolved={resolved} skipped={skipped}")  # noqa: T201
    elif arguments.collect_corp_codes:
        observed, saved = anyio.run(collect_dart_corp_codes)
        print(f"corp_codes observed={observed} new_versions={saved}")  # noqa: T201
    elif arguments.universe_dividends:
        symbols, observations, failed, missing = anyio.run(
            collect_universe_dividends,
            arguments.start_date,
            arguments.end_date,
        )
        report = (
            f"dividends symbols={symbols} observations={observations} "
            f"failed={failed} missing_corp_codes={len(missing)}"
        )
        print(report)  # noqa: T201
    elif arguments.etf_distributions:
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
