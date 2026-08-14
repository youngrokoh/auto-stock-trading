import logging
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final, final, override
from zoneinfo import ZoneInfo

import anyio
import httpx2
from pydantic import SecretStr, ValidationError

from auto_stock_trading.adapters.brokers.kis_contracts import KisTokenResponse

logger = logging.getLogger(__name__)
_AUTH_ENDPOINT = "/oauth2/tokenP"
_HTTP_ERROR_STATUS = 400
_DEFAULT_MINIMUM_INTERVAL_SECONDS: Final = 1.05

_LIMITS = httpx2.Limits(
    max_connections=200,
    max_keepalive_connections=40,
    keepalive_expiry=30.0,
)
_TIMEOUT = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
_SOCKET_OPTIONS: list[tuple[int, int, int]] = [
    (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
]


@dataclass(frozen=True, slots=True)
class KisCredentials:
    app_key: SecretStr
    app_secret: SecretStr


@dataclass(frozen=True, slots=True)
class KisRawResponse:
    endpoint: str
    request_fingerprint: str
    received_at: datetime
    payload_json: str


@dataclass(frozen=True, slots=True)
class _CachedToken:
    value: SecretStr
    expires_at: datetime


@final
@dataclass(frozen=True, slots=True)
class KisConfigurationError(Exception):
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@final
@dataclass(frozen=True, slots=True)
class KisTransportError(Exception):
    endpoint: str
    status_code: int | None

    @override
    def __str__(self) -> str:
        suffix = "network failure" if self.status_code is None else f"HTTP {self.status_code}"
        return f"KIS request failed at {self.endpoint}: {suffix}"


async def _log_request(request: httpx2.Request) -> None:
    request.extensions["request_started_at"] = time.perf_counter()


async def _log_response(response: httpx2.Response) -> None:
    started_at = response.request.extensions.get("request_started_at")
    elapsed = time.perf_counter() - started_at if isinstance(started_at, float) else 0.0
    logger.info(
        "KIS HTTP %s %s -> %d in %.3fs",
        response.request.method,
        response.request.url.path,
        response.status_code,
        elapsed,
    )


def create_kis_http_client(base_url: str) -> httpx2.AsyncClient:
    transport = httpx2.AsyncHTTPTransport(
        http2=True,
        retries=3,
        limits=_LIMITS,
        socket_options=_SOCKET_OPTIONS,
    )
    return httpx2.AsyncClient(
        base_url=base_url,
        transport=transport,
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"Accept": "application/json"},
        event_hooks={"request": [_log_request], "response": [_log_response]},
    )


@final
class KisHttpClient:
    _SEOUL: ClassVar[ZoneInfo] = ZoneInfo("Asia/Seoul")

    def __init__(
        self,
        client: httpx2.AsyncClient,
        credentials: KisCredentials,
        *,
        minimum_interval_seconds: float = _DEFAULT_MINIMUM_INTERVAL_SECONDS,
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._minimum_interval_seconds = minimum_interval_seconds
        self._token: _CachedToken | None = None
        self._token_lock = anyio.Lock()
        self._request_lock = anyio.Lock()
        self._last_request_at: float | None = None

    async def get(
        self,
        *,
        endpoint: str,
        transaction_id: str,
        params: dict[str, str],
        request_fingerprint: str,
    ) -> KisRawResponse:
        token = await self._access_token()
        response = await self._request(
            "GET",
            endpoint,
            headers={
                "authorization": f"Bearer {token.get_secret_value()}",
                "appkey": self._credentials.app_key.get_secret_value(),
                "appsecret": self._credentials.app_secret.get_secret_value(),
                "tr_id": transaction_id,
                "custtype": "P",
            },
            params=params,
        )
        return KisRawResponse(
            endpoint=endpoint,
            request_fingerprint=request_fingerprint,
            received_at=datetime.now(UTC),
            payload_json=response.text,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _access_token(self) -> SecretStr:
        now = datetime.now(UTC)
        if self._token is not None and self._token.expires_at > now + timedelta(minutes=1):
            return self._token.value
        async with self._token_lock:
            now = datetime.now(UTC)
            if self._token is not None and self._token.expires_at > now + timedelta(minutes=1):
                return self._token.value
            response = await self._request(
                "POST",
                _AUTH_ENDPOINT,
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "client_credentials",
                    "appkey": self._credentials.app_key.get_secret_value(),
                    "appsecret": self._credentials.app_secret.get_secret_value(),
                },
            )
            try:
                token_response = KisTokenResponse.model_validate_json(response.text)
                expires_at = (
                    datetime.strptime(
                        token_response.access_token_token_expired,
                        "%Y-%m-%d %H:%M:%S",
                    )
                    .replace(tzinfo=self._SEOUL)
                    .astimezone(UTC)
                )
            except (ValidationError, ValueError) as error:
                raise KisTransportError(_AUTH_ENDPOINT, response.status_code) from error
            self._token = _CachedToken(token_response.access_token, expires_at)
            return self._token.value

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        json: dict[str, str] | None = None,
    ) -> httpx2.Response:
        async with self._request_lock:
            now = anyio.current_time()
            if self._last_request_at is not None:
                wait_seconds = self._minimum_interval_seconds - (now - self._last_request_at)
                if wait_seconds > 0:
                    await anyio.sleep(wait_seconds)
            try:
                response = await self._client.request(
                    method,
                    endpoint,
                    headers=headers,
                    params=params,
                    json=json,
                )
            except httpx2.HTTPError as error:
                raise KisTransportError(endpoint, None) from error
            finally:
                self._last_request_at = anyio.current_time()
        if response.status_code >= _HTTP_ERROR_STATUS:
            raise KisTransportError(endpoint, response.status_code)
        return response
