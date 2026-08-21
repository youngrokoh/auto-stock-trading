import argparse
from datetime import UTC, datetime, timedelta
from typing import Final, final
from zoneinfo import ZoneInfo

import anyio

from auto_stock_trading.adapters.database.fundamental_disclosure_store import (
    PostgresDisclosureStore,
)
from auto_stock_trading.adapters.database.fundamental_statement_reader import (
    PostgresFinancialReportReader,
)
from auto_stock_trading.adapters.database.fundamental_statement_store import (
    PostgresFinancialReportStore,
)
from auto_stock_trading.adapters.database.reference_corp_code_store import PostgresCorpCodeStore
from auto_stock_trading.adapters.disclosures.opendart_disclosures import (
    DartDisclosureAdapter,
)
from auto_stock_trading.adapters.disclosures.opendart_financials import (
    DartFinancialStatementAdapter,
    FinancialStatementTarget,
)
from auto_stock_trading.adapters.disclosures.opendart_http import (
    DartHttpClient,
    create_dart_http_client,
)
from auto_stock_trading.application.disclosures import DisclosureCollector
from auto_stock_trading.application.financial_statements import (
    FinancialCollection,
    FinancialStatementCollector,
    ReportKey,
    ReportPeriod,
    collection_plan,
)
from auto_stock_trading.application.financial_statements_universe import (
    UniverseStatementCollection,
    UniverseStatementResult,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker.corporate_actions import load_dart_api_key

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_DEFAULT_TARGET: Final = FinancialStatementTarget(symbol="005930", corp_code="00126380")
_DISCLOSURE_WINDOW_DAYS: Final = 365


class Arguments(argparse.Namespace):
    symbol: str = _DEFAULT_TARGET.symbol
    corp_code: str = _DEFAULT_TARGET.corp_code
    collect_disclosures: bool = False
    universe_statements: bool = False
    only_missing: bool = False


@final
class _UniverseStatementSource:
    """유니버스 수집이 공용 DART 클라이언트와 저장소를 재사용하게 한다."""

    def __init__(self, client: DartHttpClient, store: PostgresFinancialReportStore) -> None:
        self._client = client
        self._store = store

    async def collect_symbol(
        self,
        symbol: str,
        corp_code: str,
        periods: tuple[ReportPeriod, ...],
        now: datetime,
        skip: frozenset[ReportKey],
    ) -> FinancialCollection:
        adapter = DartFinancialStatementAdapter(
            self._client,
            FinancialStatementTarget(symbol=symbol, corp_code=corp_code),
        )
        return await FinancialStatementCollector(adapter, self._store).collect(
            InstrumentTarget(symbol, ProductType.STOCK),
            periods,
            now,
            skip,
        )


async def collect_universe_financial_statements(
    *,
    only_missing: bool = False,
) -> UniverseStatementResult:
    settings = Settings()
    api_key = load_dart_api_key(settings)
    database_url = settings.database_url.get_secret_value()
    client = DartHttpClient(create_dart_http_client(settings.dart_base_url), api_key)
    codes = PostgresCorpCodeStore.from_url(database_url)
    store = PostgresFinancialReportStore.from_url(database_url)
    reader = PostgresFinancialReportReader.from_url(database_url)
    collection = UniverseStatementCollection(
        codes=codes,
        source=_UniverseStatementSource(client, store),
        reports=reader,
        status=store,
        only_missing=only_missing,
    )
    now = datetime.now(UTC)
    try:
        return await collection.run(collection_plan(now.astimezone(_SEOUL).date()), now)
    finally:
        await client.close()
        await codes.close()
        await store.close()
        await reader.close()


async def collect_financial_statements(
    symbol: str = _DEFAULT_TARGET.symbol,
    corp_code: str = _DEFAULT_TARGET.corp_code,
) -> tuple[int, int]:
    settings = Settings()
    api_key = load_dart_api_key(settings)
    source = DartFinancialStatementAdapter(
        DartHttpClient(create_dart_http_client(settings.dart_base_url), api_key),
        FinancialStatementTarget(symbol=symbol, corp_code=corp_code),
    )
    store = PostgresFinancialReportStore.from_url(settings.database_url.get_secret_value())
    collector = FinancialStatementCollector(source, store)
    now = datetime.now(UTC)
    periods = collection_plan(now.astimezone(_SEOUL).date())
    try:
        result = await collector.collect(
            InstrumentTarget(symbol, ProductType.STOCK),
            periods,
            now,
        )
    finally:
        await source.close()
        await store.close()
    return result.saved, result.skipped


async def collect_disclosures(
    symbol: str = _DEFAULT_TARGET.symbol,
    corp_code: str = _DEFAULT_TARGET.corp_code,
) -> tuple[int, int]:
    settings = Settings()
    api_key = load_dart_api_key(settings)
    source = DartDisclosureAdapter(
        DartHttpClient(create_dart_http_client(settings.dart_base_url), api_key),
        symbol=symbol,
        corp_code=corp_code,
    )
    store = PostgresDisclosureStore.from_url(settings.database_url.get_secret_value())
    collector = DisclosureCollector(source, store)
    now = datetime.now(UTC)
    end_date = now.astimezone(_SEOUL).date()
    start_date = end_date - timedelta(days=_DISCLOSURE_WINDOW_DAYS)
    try:
        result = await collector.collect(
            InstrumentTarget(symbol, ProductType.STOCK),
            start_date,
            end_date,
            now,
        )
    finally:
        await source.close()
        await store.close()
    return result.saved, result.observed


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--symbol", default=_DEFAULT_TARGET.symbol)
    _ = parser.add_argument("--corp-code", default=_DEFAULT_TARGET.corp_code)
    _ = parser.add_argument("--collect-disclosures", action="store_true")
    _ = parser.add_argument("--universe-statements", action="store_true")
    _ = parser.add_argument("--only-missing", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.universe_statements:
        result = anyio.run(
            lambda: collect_universe_financial_statements(only_missing=arguments.only_missing)
        )
        report = (
            f"statements symbols={result.symbols} saved={result.saved} "
            f"skipped={result.skipped} existing={result.existing} "
            f"failed={len(result.failed_symbols)}"
            f"{':' + ','.join(result.failed_symbols) if result.failed_symbols else ''} "
            f"missing_corp_codes={len(result.missing_corp_codes)} "
            f"quota_exhausted={result.quota_exhausted} "
            f"remaining={len(result.remaining_symbols)}"
            f"{':' + ','.join(result.remaining_symbols) if result.remaining_symbols else ''}"
        )
        print(report)  # noqa: T201
    elif arguments.collect_disclosures:
        _ = anyio.run(collect_disclosures, arguments.symbol, arguments.corp_code)
    else:
        _ = anyio.run(collect_financial_statements, arguments.symbol, arguments.corp_code)


if __name__ == "__main__":
    main()
