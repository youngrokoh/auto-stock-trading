from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from auto_stock_trading.adapters.brokers.kis_coordination import kis_coordination_scope
from auto_stock_trading.adapters.brokers.kis_coordination_valkey import (
    ValkeyKisRequestCoordinator,
)
from auto_stock_trading.adapters.brokers.kis_http import (
    KisConfigurationError,
    KisHttpClient,
    create_kis_http_client,
)
from auto_stock_trading.adapters.brokers.kis_market_calendar import KisMarketCalendarVerifier
from auto_stock_trading.adapters.database.market_calendar_repository import (
    PostgresMarketCalendarRepository,
)
from auto_stock_trading.adapters.exchanges.krx_composite_calendar import (
    KrxCompositeCalendarSource,
)
from auto_stock_trading.adapters.exchanges.krx_market_calendar import (
    KrxHttpClient,
    KrxMarketCalendarAdapter,
    create_krx_http_client,
)
from auto_stock_trading.adapters.exchanges.krx_trading_hours_notices import (
    KrxTradingHoursHttpClient,
    KrxTradingHoursNoticeAdapter,
)
from auto_stock_trading.application.market_calendar import (
    KisCalendarConfirmer,
    KrxCalendarCollector,
)
from auto_stock_trading.domain.market_data.calendar import (
    CalendarSessionKey,
    CalendarSessionRange,
    MarketSessionType,
)
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import load_kis_credentials

_SEOUL: Final = ZoneInfo("Asia/Seoul")


async def collect_krx_market_calendar(
    year: int | None = None,
    settings: Settings | None = None,
) -> int:
    runtime_settings = settings or Settings()
    selected_year = year if year is not None else datetime.now(_SEOUL).year
    query = CalendarSessionRange(
        "KR",
        "XKRX",
        date(selected_year, 1, 1),
        date(selected_year, 12, 31),
    )
    annual_source = KrxMarketCalendarAdapter(
        KrxHttpClient(create_krx_http_client(runtime_settings.krx_base_url))
    )
    notice_source = KrxTradingHoursNoticeAdapter(
        KrxTradingHoursHttpClient(
            create_krx_http_client(runtime_settings.krx_open_base_url),
            create_krx_http_client(runtime_settings.krx_attachment_base_url),
        )
    )
    source = KrxCompositeCalendarSource(annual_source, notice_source)
    store = PostgresMarketCalendarRepository.from_url(
        runtime_settings.database_url.get_secret_value()
    )
    collector = KrxCalendarCollector(source, store)
    try:
        records = await collector.collect(query, datetime.now(UTC))
    finally:
        await source.close()
        await store.close()
    return len(records)


async def confirm_today_market_calendar(settings: Settings | None = None) -> str:
    runtime_settings = settings or Settings()
    if runtime_settings.kis_environment is not KisEnvironment.LIVE:
        message = "KIS market calendar confirmation requires the live environment"
        raise KisConfigurationError(message)
    credentials = load_kis_credentials(runtime_settings)
    trading_date = datetime.now(_SEOUL).date()
    http_client = KisHttpClient(
        create_kis_http_client(runtime_settings.kis_base_url),
        credentials,
        ValkeyKisRequestCoordinator.from_url(
            runtime_settings.valkey_url.get_secret_value(),
            kis_coordination_scope(
                runtime_settings.kis_environment.value,
                credentials.app_key,
                credentials.app_secret,
            ),
        ),
    )
    verifier = KisMarketCalendarVerifier(http_client)
    store = PostgresMarketCalendarRepository.from_url(
        runtime_settings.database_url.get_secret_value()
    )
    confirmer = KisCalendarConfirmer(verifier, store)
    key = CalendarSessionKey("KR", "XKRX", trading_date, MarketSessionType.REGULAR)
    try:
        _record = await confirmer.confirm(key, datetime.now(UTC))
    finally:
        await verifier.close()
        await store.close()
    return trading_date.isoformat()
