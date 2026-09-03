"""주문 계획·정정 CLI가 같은 어댑터 조립을 쓰게 하는 공용 배선."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from auto_stock_trading.adapters.brokers.kis_account import KisAccountAdapter
from auto_stock_trading.adapters.brokers.kis_coordination import kis_coordination_scope
from auto_stock_trading.adapters.brokers.kis_coordination_valkey import (
    ValkeyKisRequestCoordinator,
)
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisHttpClient,
    create_kis_http_client,
)
from auto_stock_trading.adapters.brokers.kis_market_data import KisMarketDataAdapter
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.database.market_data_etf_classification import (
    PostgresEtfClassificationSource,
)
from auto_stock_trading.adapters.database.market_data_repository import (
    PostgresMarketDataRepository,
)
from auto_stock_trading.adapters.database.market_data_stock_store import PostgresStockStore
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.planning import OrderPlanner
from auto_stock_trading.application.trading.sector_sources import ChainedSectorSource
from auto_stock_trading.settings.runtime import KisEnvironment
from auto_stock_trading.worker.kis_credentials import load_kis_account, load_kis_credentials

if TYPE_CHECKING:
    from auto_stock_trading.domain.orders.account import AccountSnapshotObservation
    from auto_stock_trading.settings.runtime import Settings

_PAPER_ONLY = "order planning is allowed in the paper environment only"


@final
class MissingAccountSource:
    """계좌 secret이 없을 때 계좌 조회 없는 차단 경로만 허용하는 fail-closed 소스."""

    def __init__(self, error: KisConfigurationError) -> None:
        self._error = error

    async def fetch_balance(self) -> AccountSnapshotObservation:
        raise self._error

    async def close(self) -> None:
        return None


def http_client(settings: Settings) -> KisHttpClient:
    credentials = load_kis_credentials(settings)
    return KisHttpClient(
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


def paper_settings(settings: Settings) -> Settings:
    if settings.kis_environment is not KisEnvironment.PAPER:
        raise RuntimeError(_PAPER_ONLY)
    return settings


@final
@dataclass(frozen=True, slots=True)
class PlannerBundle:
    """플래너와 그것이 소유한 자원. 실행이 끝나면 모두 닫는다."""

    planner: OrderPlanner
    store: PostgresTradingStore
    calendar: PostgresMarketCalendarRepository
    instruments: PostgresMarketDataRepository
    quotes: KisMarketDataAdapter
    accounts: KisAccountAdapter | MissingAccountSource
    sectors: SectorSources

    async def close(self) -> None:
        await self.quotes.close()
        await self.accounts.close()
        await self.calendar.close()
        await self.instruments.close()
        await self.sectors.close()
        await self.store.close()


@final
@dataclass(frozen=True, slots=True)
class SectorSources:
    """플래너가 쓰는 분류 원천 묶음. 조립은 여기 한 곳이다.

    주식은 KOSPI200 업종 코드, ETF는 추종 지수다(ADR-0021). 키가 겹치지 않으면 한도 계산에는 문제가
    없다 — 업종 한도는 같은 키끼리의 합에만 걸린다. 2026-09-03에 CLI 경로와 예약 경로가 따로
    조립하다가 예약 경로만 ETF 분류를 빠뜨린 적이 있어, 두 경로가 이 함수를 함께 쓴다.
    """

    stocks: PostgresStockStore
    etfs: PostgresEtfClassificationSource

    @property
    def chained(self) -> ChainedSectorSource:
        return ChainedSectorSource(self.stocks, self.etfs)

    async def close(self) -> None:
        await self.etfs.close()
        await self.stocks.close()


def sector_sources(database_url: str) -> SectorSources:
    return SectorSources(
        stocks=PostgresStockStore.from_url(database_url),
        etfs=PostgresEtfClassificationSource.from_url(database_url),
    )


def planner_bundle(settings: Settings) -> PlannerBundle:
    database_url = paper_settings(settings).database_url.get_secret_value()
    calendar = PostgresMarketCalendarRepository.from_url(database_url)
    instruments = PostgresMarketDataRepository.from_url(database_url)
    store = PostgresTradingStore.from_url(database_url)
    sectors = sector_sources(database_url)
    quotes = KisMarketDataAdapter(http_client(settings), instrument_details_available=False)
    accounts: KisAccountAdapter | MissingAccountSource
    try:
        account = load_kis_account(settings)
    except KisConfigurationError as error:
        accounts = MissingAccountSource(error)
    else:
        accounts = KisAccountAdapter(http_client(settings), account, paper=True)
    return PlannerBundle(
        planner=OrderPlanner(
            calendar=calendar,
            instruments=instruments,
            quotes=quotes,
            accounts=accounts,
            store=store,
            sectors=sectors.chained,
        ),
        store=store,
        calendar=calendar,
        instruments=instruments,
        quotes=quotes,
        accounts=accounts,
        sectors=sectors,
    )
