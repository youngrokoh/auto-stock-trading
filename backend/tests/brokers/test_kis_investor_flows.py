from datetime import UTC, date, datetime

import anyio

from auto_stock_trading.adapters.brokers.kis_investor_flows import (
    INVESTOR_FLOWS_ENDPOINT,
    KisInvestorFlowAdapter,
)
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from tests.brokers.kis_fixture import create_fixture_handler_client

_TARGET = InstrumentTarget("005930", ProductType.STOCK)


def test_investor_flows_exclude_the_current_seoul_trading_date() -> None:
    async def run() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisInvestorFlowAdapter(client)
        try:
            # 2026-08-14 19:00 KST — 당일(8/14) 행은 잠정치이므로 제외된다
            bundle = await adapter.fetch_flows(_TARGET, datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
        finally:
            await adapter.close()

        assert handler.market_requests[-1].url.path == INVESTOR_FLOWS_ENDPOINT
        assert tuple(flow.trading_date for flow in bundle.flows) == (
            date(2026, 8, 13),
            date(2026, 8, 12),
        )
        first = bundle.flows[0]
        assert first.symbol == _TARGET.symbol
        assert first.individual_net_quantity == -5097051
        assert first.foreign_net_quantity == -401379
        assert first.institution_net_quantity == 5544777
        assert first.individual_net_value == -1372371
        assert first.foreign_net_value == -103862
        assert first.institution_net_value == 1488708
        assert first.source == "KIS"

    anyio.run(run)


def test_investor_flows_keep_all_completed_days_after_the_date_moves_on() -> None:
    async def run() -> None:
        client, _ = create_fixture_handler_client()
        adapter = KisInvestorFlowAdapter(client)
        try:
            bundle = await adapter.fetch_flows(_TARGET, datetime(2026, 8, 17, 1, 0, tzinfo=UTC))
        finally:
            await adapter.close()

        assert tuple(flow.trading_date for flow in bundle.flows) == (
            date(2026, 8, 14),
            date(2026, 8, 13),
            date(2026, 8, 12),
        )
        assert bundle.raw.request_fingerprint == "investor_flows:005930"

    anyio.run(run)
