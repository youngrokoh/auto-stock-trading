import argparse
from datetime import UTC, datetime
from typing import Final
from zoneinfo import ZoneInfo

import anyio

from auto_stock_trading.adapters.database.fundamental_statement_store import (
    PostgresFinancialReportStore,
)
from auto_stock_trading.adapters.disclosures.opendart_financials import (
    DartFinancialStatementAdapter,
    FinancialStatementTarget,
)
from auto_stock_trading.adapters.disclosures.opendart_http import (
    DartHttpClient,
    create_dart_http_client,
)
from auto_stock_trading.application.financial_statements import (
    FinancialStatementCollector,
    collection_plan,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings
from auto_stock_trading.worker.corporate_actions import load_dart_api_key

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_DEFAULT_TARGET: Final = FinancialStatementTarget(symbol="005930", corp_code="00126380")


class Arguments(argparse.Namespace):
    symbol: str = _DEFAULT_TARGET.symbol
    corp_code: str = _DEFAULT_TARGET.corp_code


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


def main() -> None:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--symbol", default=_DEFAULT_TARGET.symbol)
    _ = parser.add_argument("--corp-code", default=_DEFAULT_TARGET.corp_code)
    arguments = parser.parse_args(namespace=Arguments())
    _ = anyio.run(collect_financial_statements, arguments.symbol, arguments.corp_code)


if __name__ == "__main__":
    main()
