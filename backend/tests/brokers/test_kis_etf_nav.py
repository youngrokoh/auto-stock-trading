from datetime import UTC, date, datetime
from decimal import Decimal

import anyio

from auto_stock_trading.adapters.brokers.kis_etf_nav import (
    ETF_PRICE_ENDPOINT,
    KisEtfNavAdapter,
)
from tests.brokers.kis_fixture import create_fixture_handler_client

_NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


def test_etf_nav_snapshot_normalizes_source_fields_verbatim() -> None:
    async def run() -> None:
        client, handler = create_fixture_handler_client()
        adapter = KisEtfNavAdapter(client)
        try:
            observation = await adapter.fetch_snapshot("069500")
        finally:
            await adapter.close()

        assert handler.market_requests[-1].url.path == ETF_PRICE_ENDPOINT
        snapshot = observation.snapshot
        assert snapshot.symbol == "069500"
        assert snapshot.price == Decimal(110060)
        assert snapshot.nav == Decimal("110371.90")
        assert snapshot.divergence_rate == Decimal("-0.28")
        assert snapshot.tracking_error == Decimal("0.39")
        assert snapshot.tracking_multiple == Decimal("1.00")
        assert snapshot.net_asset_total == 260643
        assert snapshot.listed_shares == 236150000
        assert snapshot.manager == "삼성자산운용(ETF)"
        assert snapshot.index_name == "KOSPI200"
        assert snapshot.listing_date == date(2002, 10, 14)
        assert snapshot.volume == 495
        assert snapshot.previous_volume == 17088038
        assert snapshot.currency == "KRW"
        assert snapshot.source == "KIS"
        assert observation.raw.request_fingerprint == "etf_nav:069500"

    anyio.run(run)
