from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auto_stock_trading.adapters.database.fundamental_disclosure_reader import (
    PostgresDisclosureReader,
)
from auto_stock_trading.adapters.database.fundamental_statement_reader import (
    PostgresFinancialReportReader,
)
from auto_stock_trading.adapters.database.gate_reader import PostgresGateReader
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
from auto_stock_trading.adapters.database.market_data_share_class_store import (
    PostgresShareClassStore,
)
from auto_stock_trading.adapters.database.market_data_stock_store import PostgresStockStore
from auto_stock_trading.adapters.database.strategy_backtest_reader import (
    PostgresBacktestReader,
)
from auto_stock_trading.adapters.database.trading_reader import PostgresTradingReader
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.adapters.health import PostgresHealthProbe, ValkeyHealthProbe
from auto_stock_trading.api.backtests import create_backtests_router
from auto_stock_trading.api.fundamentals import create_fundamentals_router
from auto_stock_trading.api.gate import GateReader, create_gate_router
from auto_stock_trading.api.health import create_health_router
from auto_stock_trading.api.market_data import create_market_data_router
from auto_stock_trading.api.market_data_adjusted import create_market_data_adjusted_router
from auto_stock_trading.api.market_data_etf import create_market_data_etf_router
from auto_stock_trading.api.trading import create_trading_router
from auto_stock_trading.api.trading.router import Clock, TradingReader, utc_now
from auto_stock_trading.application.adjusted_prices import (
    AdjustedPriceReader,
    CorporateActionReader,
)
from auto_stock_trading.application.backtests.reader import BacktestReader
from auto_stock_trading.application.disclosures import DisclosureReader
from auto_stock_trading.application.etf import EtfReader
from auto_stock_trading.application.financial_indicators import (
    SectorSource,
    ShareClassSource,
)
from auto_stock_trading.application.financial_statements import FinancialReportReader
from auto_stock_trading.application.health import HealthProbe, HealthService
from auto_stock_trading.application.market_data import MarketDataReader
from auto_stock_trading.application.trading.startup import (
    AutomationResetStore,
    reset_automation_on_start,
)
from auto_stock_trading.settings.runtime import KisEnvironment, Settings

if TYPE_CHECKING:
    from datetime import datetime

ProbeFactory = Callable[[], HealthProbe]
MarketDataReaderFactory = Callable[[], MarketDataReader]
CorporateActionReaderFactory = Callable[[], CorporateActionReader]
AdjustedPriceReaderFactory = Callable[[], AdjustedPriceReader]
FinancialReportReaderFactory = Callable[[], FinancialReportReader]
DisclosureReaderFactory = Callable[[], DisclosureReader]
EtfReaderFactory = Callable[[], EtfReader]
BacktestReaderFactory = Callable[[], BacktestReader]
TradingReaderFactory = Callable[[], TradingReader]
SectorSourceFactory = Callable[[], SectorSource]
ShareClassSourceFactory = Callable[[], ShareClassSource]


class ClosableAutomationReset(AutomationResetStore, Protocol):
    """기동 리셋 저장소는 앱이 직접 열고 닫는다. 요청 경로에서는 쓰지 않는다."""

    async def close(self) -> None: ...


AutomationResetFactory = Callable[[], ClosableAutomationReset]
GateReaderFactory = Callable[[], GateReader]


def _resolve[T](factory: Callable[[], T] | None, default: Callable[[], T]) -> T:
    """주입된 팩토리가 없으면 실제 인프라를 만든다. 테스트가 쓰는 이음새다."""
    return (factory or default)()


def _reset_factory(
    factory: AutomationResetFactory | None,
    database_url: str,
) -> AutomationResetFactory:
    return factory or (lambda: PostgresTradingStore.from_url(database_url))


async def _reset_automation(
    factory: AutomationResetFactory,
    environment: str,
    now: datetime,
) -> None:
    store = factory()
    try:
        _ = await reset_automation_on_start(store, environment, now)
    finally:
        await store.close()


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
    backtest_reader_factory: BacktestReaderFactory | None = None,
    trading_reader_factory: TradingReaderFactory | None = None,
    sector_source_factory: SectorSourceFactory | None = None,
    share_class_source_factory: ShareClassSourceFactory | None = None,
    automation_reset_factory: AutomationResetFactory | None = None,
    gate_reader_factory: GateReaderFactory | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    database_url = runtime_settings.database_url.get_secret_value()
    health_service = HealthService(
        database=_resolve(
            database_probe_factory,
            lambda: PostgresHealthProbe.from_url(database_url),
        ),
        cache=_resolve(
            cache_probe_factory,
            lambda: ValkeyHealthProbe.from_url(
                runtime_settings.valkey_url.get_secret_value(),
            ),
        ),
    )
    market_data_reader = _resolve(
        market_data_reader_factory,
        lambda: PostgresMarketDataRepository.from_url(database_url),
    )
    corporate_action_reader = _resolve(
        corporate_action_reader_factory,
        lambda: PostgresCorporateActionReader.from_url(database_url),
    )
    adjusted_price_reader = _resolve(
        adjusted_price_reader_factory,
        lambda: PostgresAdjustedPriceReader.from_url(database_url),
    )
    financial_report_reader = _resolve(
        financial_report_reader_factory,
        lambda: PostgresFinancialReportReader.from_url(database_url),
    )
    disclosure_reader = _resolve(
        disclosure_reader_factory,
        lambda: PostgresDisclosureReader.from_url(database_url),
    )
    etf_reader = _resolve(etf_reader_factory, lambda: PostgresEtfReader.from_url(database_url))
    backtest_reader = _resolve(
        backtest_reader_factory,
        lambda: PostgresBacktestReader.from_url(database_url),
    )
    trading_reader = _resolve(
        trading_reader_factory,
        lambda: PostgresTradingReader.from_url(database_url),
    )
    sector_source = _resolve(
        sector_source_factory,
        lambda: PostgresStockStore.from_url(database_url),
    )
    share_class_source = _resolve(
        share_class_source_factory,
        lambda: PostgresShareClassStore.from_url(database_url),
    )
    gate_reader = _resolve(gate_reader_factory, lambda: PostgresGateReader.from_url(database_url))
    automation_reset = _reset_factory(automation_reset_factory, database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # 정책 §6: 서버 기동은 상태 머신의 입력이다. 사람이 다시 켜야 주문이 나간다.
        await _reset_automation(
            automation_reset,
            runtime_settings.kis_environment.value,
            (clock or utc_now)(),
        )
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
            await backtest_reader.close()
            await trading_reader.close()
            await sector_source.close()
            await share_class_source.close()
            await gate_reader.close()

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
        create_fundamentals_router(
            market_data_reader,
            financial_report_reader,
            disclosure_reader,
            sector_source,
            share_class_source,
        )
    )
    app.include_router(create_backtests_router(backtest_reader))
    app.include_router(
        create_gate_router(
            gate_reader,
            runtime_settings.kis_environment.value,
            live_enabled=runtime_settings.kis_environment is not KisEnvironment.PAPER,
            **({"clock": clock} if clock is not None else {}),
        )
    )
    app.include_router(
        create_trading_router(
            trading_reader,
            runtime_settings.kis_environment.value,
            *((clock,) if clock is not None else ()),
        )
    )
    return app


app = create_app()
