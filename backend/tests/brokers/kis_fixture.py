from pathlib import Path
from urllib.parse import parse_qs

import httpx2
from pydantic import SecretStr

from auto_stock_trading.adapters.brokers.kis_account import BALANCE_ENDPOINT
from auto_stock_trading.adapters.brokers.kis_coordination import (
    InMemoryKisRequestCoordinator,
    KisCoordinationConfig,
)
from auto_stock_trading.adapters.brokers.kis_etf_nav import ETF_PRICE_ENDPOINT
from auto_stock_trading.adapters.brokers.kis_http import KisCredentials, KisHttpClient
from auto_stock_trading.adapters.brokers.kis_investor_flows import INVESTOR_FLOWS_ENDPOINT
from auto_stock_trading.adapters.brokers.kis_market_data import (
    DAILY_BARS_ENDPOINT,
    INSTRUMENT_ENDPOINT,
    QUOTE_ENDPOINT,
    KisMarketDataAdapter,
)
from auto_stock_trading.adapters.brokers.kis_orders import (
    DAILY_FILLS_ENDPOINT,
    ORDER_ENDPOINT,
    REVISE_CANCEL_ENDPOINT,
)

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "kis"


class KisFixtureHandler:
    token_requests: int
    market_requests: list[httpx2.Request]
    _token_filenames: tuple[str, ...]
    _order_filename: str
    _cancel_filename: str
    _fills_filename: str

    def __init__(
        self,
        token_filenames: tuple[str, ...],
        order_filename: str = "order_cash.json",
        cancel_filename: str = "order_cancel.json",
        fills_filename: str = "daily_fills.json",
    ) -> None:
        self.token_requests = 0
        self.market_requests = []
        self._token_filenames = token_filenames
        self._order_filename = order_filename
        self._cancel_filename = cancel_filename
        self._fills_filename = fills_filename

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/oauth2/tokenP":
            self.token_requests += 1
            index = min(self.token_requests - 1, len(self._token_filenames) - 1)
            return self._response(request, self._token_filenames[index])
        self.market_requests.append(request)
        account_filename = {
            BALANCE_ENDPOINT: "account_balance.json",
            ORDER_ENDPOINT: self._order_filename,
            REVISE_CANCEL_ENDPOINT: self._cancel_filename,
            DAILY_FILLS_ENDPOINT: self._fills_filename,
        }.get(request.url.path)
        if account_filename is not None:
            return self._response(request, account_filename)
        query = parse_qs(request.url.query.decode())
        symbols = query.get("PDNO") or query.get("FID_INPUT_ISCD")
        if not symbols:
            return httpx2.Response(400, request=request)
        symbol = symbols[0]
        suffix_by_path = {
            INSTRUMENT_ENDPOINT: "instrument",
            QUOTE_ENDPOINT: "quote",
            DAILY_BARS_ENDPOINT: "daily_bars",
            INVESTOR_FLOWS_ENDPOINT: "investor",
            ETF_PRICE_ENDPOINT: "etfprice",
        }
        suffix = suffix_by_path.get(request.url.path)
        if suffix is None:
            return httpx2.Response(404, request=request)
        return self._response(request, f"{symbol}_{suffix}.json")

    @staticmethod
    def _response(request: httpx2.Request, filename: str) -> httpx2.Response:
        return httpx2.Response(
            200,
            request=request,
            headers={"Content-Type": "application/json"},
            text=(_FIXTURE_ROOT / filename).read_text(encoding="utf-8"),
        )


def create_fixture_handler_client(
    token_filenames: tuple[str, ...] = ("token.json",),
    *,
    order_filename: str = "order_cash.json",
    cancel_filename: str = "order_cancel.json",
    fills_filename: str = "daily_fills.json",
) -> tuple[KisHttpClient, KisFixtureHandler]:
    handler = KisFixtureHandler(
        token_filenames,
        order_filename=order_filename,
        cancel_filename=cancel_filename,
        fills_filename=fills_filename,
    )
    client = httpx2.AsyncClient(
        base_url="https://kis.example.test",
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
        follow_redirects=True,
    )
    http_client = KisHttpClient(
        client,
        KisCredentials(SecretStr("fixture-app-key"), SecretStr("fixture-app-secret")),
        InMemoryKisRequestCoordinator(KisCoordinationConfig(minimum_interval_seconds=0)),
    )
    return http_client, handler


def create_fixture_adapter(
    token_filenames: tuple[str, ...] = ("token.json",),
    *,
    instrument_details_available: bool = True,
) -> tuple[KisMarketDataAdapter, KisFixtureHandler]:
    http_client, handler = create_fixture_handler_client(token_filenames)
    return KisMarketDataAdapter(
        http_client,
        instrument_details_available=instrument_details_available,
    ), handler
