from pathlib import Path

import httpx2

from auto_stock_trading.adapters.disclosures.kodex_distributions import (
    KODEX_DISTRIBUTION_ENDPOINT,
    KodexDistributionAdapter,
    KodexDistributionTarget,
)

_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "kodex"
_DEFAULT_TARGET = KodexDistributionTarget(symbol="069500", fund_id="2ETF01")


class KodexFixtureHandler:
    requests: list[httpx2.Request]
    _fixture_filename: str

    def __init__(self, fixture_filename: str) -> None:
        self.requests = []
        self._fixture_filename = fixture_filename

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path != KODEX_DISTRIBUTION_ENDPOINT:
            return httpx2.Response(404, request=request)
        return httpx2.Response(
            200,
            request=request,
            headers={"Content-Type": "application/json"},
            text=(_FIXTURE_ROOT / self._fixture_filename).read_text(encoding="utf-8"),
        )


def create_fixture_adapter(
    fixture_filename: str = "divid_info_2ETF01.json",
    target: KodexDistributionTarget = _DEFAULT_TARGET,
) -> tuple[KodexDistributionAdapter, KodexFixtureHandler]:
    handler = KodexFixtureHandler(fixture_filename)
    client = httpx2.AsyncClient(
        base_url="https://kodex.example.test",
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
    )
    return KodexDistributionAdapter(client, target), handler
