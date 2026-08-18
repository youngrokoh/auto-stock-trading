from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auto_stock_trading.adapters.database.fundamental_disclosure_reader import (
    PostgresDisclosureReader,
)
from auto_stock_trading.adapters.database.fundamental_statement_reader import (
    PostgresFinancialReportReader,
)
from auto_stock_trading.adapters.database.market_data_adjustment_reader import (
    PostgresAdjustedPriceReader,
)
from auto_stock_trading.adapters.database.market_data_corporate_action_reader import (
    PostgresCorporateActionReader,
)
from auto_stock_trading.adapters.database.market_data_etf_reader import PostgresEtfReader
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.health import PostgresHealthProbe, ValkeyHealthProbe
from auto_stock_trading.api.fundamentals import create_fundamentals_router
from auto_stock_trading.api.health import create_health_router
from auto_stock_trading.api.market_data import create_market_data_router
from auto_stock_trading.api.market_data_adjusted import create_market_data_adjusted_router
from auto_stock_trading.api.market_data_etf import create_market_data_etf_router
from auto_stock_trading.application.adjusted_prices import (
    AdjustedPriceReader,
    CorporateActionReader,
)
from auto_stock_trading.application.disclosures import DisclosureReader
from auto_stock_trading.application.etf import EtfReader
from auto_stock_trading.application.financial_statements import FinancialReportReader
from auto_stock_trading.application.health import HealthProbe, HealthService
from auto_stock_trading.application.market_data import MarketDataReader
from auto_stock_trading.settings.runtime import Settings

ProbeFactory = Callable[[], HealthProbe]
MarketDataReaderFactory = Callable[[], MarketDataReader]
CorporateActionReaderFactory = Callable[[], CorporateActionReader]
AdjustedPriceReaderFactory = Callable[[], AdjustedPriceReader]
FinancialReportReaderFactory = Callable[[], FinancialReportReader]
DisclosureReaderFactory = Callable[[], DisclosureReader]
EtfReaderFactory = Callable[[], EtfReader]


def create_app(  # noqa: PLR0913
    settings: Settings | None = None,
    *,
    database_probe_factory: ProbeFactory | None = None,
    cache_probe_factory: ProbeFactory | None = None,
    market_data_reader_factory: MarketDataReaderFactory | None = None,
    corporate_action_reader_factory: CorporateActionReaderFactory | None = None,
    adjusted_price_reader_factory: AdjustedPriceReaderFactory | None = None,
    financial_report_reader_factory: FinancialReportReaderFactory | None = None,
    disclosure_reader_factory: DisclosureReaderFactory | None = None,
    etf_reader_factory: EtfReaderFactory | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    database_factory = database_probe_factory or (
        lambda: PostgresHealthProbe.from_url(runtime_settings.database_url.get_secret_value())
    )
    cache_factory = cache_probe_factory or (
        lambda: ValkeyHealthProbe.from_url(runtime_settings.valkey_url.get_secret_value())
    )
    health_service = HealthService(database=database_factory(), cache=cache_factory())
    reader_factory = market_data_reader_factory or (
        lambda: PostgresMarketDataRepository.from_url(
            runtime_settings.database_url.get_secret_value()
        )
    )
    market_data_reader = reader_factory()
    action_reader_factory = corporate_action_reader_factory or (
        lambda: PostgresCorporateActionReader.from_url(
            runtime_settings.database_url.get_secret_value()
        )
    )
    corporate_action_reader = action_reader_factory()
    adjusted_reader_factory = adjusted_price_reader_factory or (
        lambda: PostgresAdjustedPriceReader.from_url(
            runtime_settings.database_url.get_secret_value()
        )
    )
    adjusted_price_reader = adjusted_reader_factory()
    financial_reader_factory = financial_report_reader_factory or (
        lambda: PostgresFinancialReportReader.from_url(
            runtime_settings.database_url.get_secret_value()
        )
    )
    financial_report_reader = financial_reader_factory()
    disclosure_factory = disclosure_reader_factory or (
        lambda: PostgresDisclosureReader.from_url(runtime_settings.database_url.get_secret_value())
    )
    disclosure_reader = disclosure_factory()
    etf_factory = etf_reader_factory or (
        lambda: PostgresEtfReader.from_url(runtime_settings.database_url.get_secret_value())
    )
    etf_reader = etf_factory()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            await health_service.close()
            await market_data_reader.close()
            await corporate_action_reader.close()
            await adjusted_price_reader.close()
            await financial_report_reader.close()
            await disclosure_reader.close()
            await etf_reader.close()

    app = FastAPI(
        title="Auto Stock Trading API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.include_router(create_health_router(health_service, runtime_settings))
    app.include_router(create_market_data_router(market_data_reader))
    app.include_router(
        create_market_data_adjusted_router(
            market_data_reader,
            corporate_action_reader,
            adjusted_price_reader,
        )
    )
    app.include_router(create_market_data_etf_router(etf_reader, corporate_action_reader))
    app.include_router(
        create_fundamentals_router(market_data_reader, financial_report_reader, disclosure_reader)
    )
    return app


app = create_app()
