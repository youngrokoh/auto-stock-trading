from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import anyio
import httpx2
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_contracts import KisInstrumentResponse
from auto_stock_trading.adapters.brokers.kis_http import KisCredentials, KisHttpClient
from auto_stock_trading.adapters.brokers.kis_mapping import instrument_from
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from tests.brokers.kis_fixture import create_fixture_adapter


def test_kis_fixture_contract_normalizes_stock_and_etf() -> None:
    async def run() -> None:
        adapter, handler = create_fixture_adapter()
        try:
            stock = await adapter.fetch_bundle(
                InstrumentTarget("005930", ProductType.STOCK),
                date(2026, 8, 12),
                date(2026, 8, 13),
            )
            etf = await adapter.fetch_bundle(
                InstrumentTarget("069500", ProductType.ETF),
                date(2026, 8, 12),
                date(2026, 8, 13),
            )
        finally:
            await adapter.close()

        assert handler.token_requests == 1
        assert len(handler.market_requests) == 6
        assert all(
            request.headers["authorization"] == "Bearer fixture-access-token"
            for request in handler.market_requests
        )
        assert stock.instrument.name == "삼성전자"
        assert stock.quote.price == Decimal(73500)
        assert tuple(bar.trading_date for bar in stock.daily_bars) == (
            date(2026, 8, 13),
            date(2026, 8, 12),
        )
        assert all(not bar.adjusted for bar in stock.daily_bars)
        assert etf.instrument.product_type is ProductType.ETF
        assert etf.instrument.name == "KODEX 200"
        assert etf.quote.price == Decimal(38250)
        assert len(etf.raw_responses) == 3

    anyio.run(run)


def test_kis_adapter_uses_daily_summary_when_instrument_details_are_unavailable() -> None:
    async def run() -> None:
        adapter, handler = create_fixture_adapter(instrument_details_available=False)
        try:
            bundle = await adapter.fetch_bundle(
                InstrumentTarget("005930", ProductType.STOCK),
                date(2026, 8, 12),
                date(2026, 8, 13),
            )
        finally:
            await adapter.close()

        assert tuple(request.url.path for request in handler.market_requests) == (
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        )
        assert bundle.instrument.name == "삼성전자"
        assert tuple(raw.operation.value for raw in bundle.raw_responses) == (
            "quote",
            "daily_bars",
        )

    anyio.run(run)


def test_expired_kis_token_is_refreshed_before_the_next_request() -> None:
    async def run() -> None:
        adapter, handler = create_fixture_adapter(("token_expired.json", "token.json"))
        try:
            _ = await adapter.fetch_bundle(
                InstrumentTarget("005930", ProductType.STOCK),
                date(2026, 8, 12),
                date(2026, 8, 13),
            )
        finally:
            await adapter.close()

        assert handler.token_requests == 2
        assert handler.market_requests[0].headers["authorization"] == (
            "Bearer expired-fixture-token"
        )
        assert handler.market_requests[1].headers["authorization"] == (
            "Bearer fixture-access-token"
        )

    anyio.run(run)


def test_instrument_source_date_uses_the_korean_market_date() -> None:
    response = KisInstrumentResponse.model_validate(
        {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "success",
            "output": {
                "pdno": "005930",
                "prdt_type_cd": "300",
                "prdt_name": "삼성전자",
                "mket_id_cd": "STK",
            },
        }
    )

    instrument = instrument_from(
        InstrumentTarget("005930", ProductType.STOCK),
        response,
        datetime(2026, 8, 13, 15, 30, tzinfo=UTC),
    )

    assert instrument.source_as_of == date(2026, 8, 14)


def test_kis_client_default_interval_respects_the_paper_rate_limit() -> None:
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    def response_for(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx2.Response(
                200,
                request=request,
                json={
                    "access_token": "fixture-access-token",
                    "token_type": "Bearer",
                    "expires_in": 86400,
                    "access_token_token_expired": "2099-08-14 12:00:00",
                },
            )
        return httpx2.Response(200, request=request, text="{}")

    client = httpx2.AsyncClient(
        base_url="https://kis.example.test",
        transport=httpx2.MockTransport(response_for),
    )
    http_client = KisHttpClient(
        client,
        KisCredentials(SecretStr("fixture-app-key"), SecretStr("fixture-app-secret")),
    )

    async def run() -> None:
        with patch("auto_stock_trading.adapters.brokers.kis_http.anyio.sleep", record_wait):
            for fingerprint in ("first", "second"):
                _ = await http_client.get(
                    endpoint="/uapi/example",
                    transaction_id="FIXTURE",
                    params={},
                    request_fingerprint=fingerprint,
                )
        await http_client.close()

    anyio.run(run)

    assert len(waits) == 2
    assert all(seconds >= 1.0 for seconds in waits)
