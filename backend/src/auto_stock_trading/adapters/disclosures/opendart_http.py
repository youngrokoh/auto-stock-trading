from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final, override

import httpx2

if TYPE_CHECKING:
    from pydantic import SecretStr

DART_LIST_ENDPOINT: Final = "/api/list.json"
DART_DOCUMENT_ENDPOINT: Final = "/api/document.xml"
_USER_AGENT: Final = "auto-stock-trading/0.1 (corporate-action integration)"
_HTTP_ERROR_STATUS: Final = 400


@final
@dataclass(frozen=True, slots=True)
class DartConfigurationError(Exception):
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@final
@dataclass(frozen=True, slots=True)
class DartTransportError(Exception):
    endpoint: str
    status_code: int | None

    @override
    def __str__(self) -> str:
        suffix = "network failure" if self.status_code is None else f"HTTP {self.status_code}"
        return f"DART request failed at {self.endpoint}: {suffix}"


@final
class DartHttpClient:
    def __init__(self, client: httpx2.AsyncClient, api_key: SecretStr) -> None:
        self._client = client
        self._api_key = api_key

    async def fetch_text(self, endpoint: str, params: dict[str, str]) -> str:
        return (await self._request(endpoint, params)).text

    async def fetch_bytes(self, endpoint: str, params: dict[str, str]) -> bytes:
        return (await self._request(endpoint, params)).content

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, endpoint: str, params: dict[str, str]) -> httpx2.Response:
        try:
            response = await self._client.get(
                endpoint,
                params={"crtfc_key": self._api_key.get_secret_value(), **params},
            )
        except httpx2.HTTPError as error:
            raise DartTransportError(endpoint, None) from error
        if response.status_code >= _HTTP_ERROR_STATUS:
            raise DartTransportError(endpoint, response.status_code)
        return response


def create_dart_http_client(base_url: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
