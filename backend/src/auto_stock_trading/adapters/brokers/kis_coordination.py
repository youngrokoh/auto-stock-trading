import hashlib
import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import ClassVar, Final, Protocol, final, override
from urllib.parse import unquote, urlsplit

import anyio
import anyio.lowlevel
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from redis.asyncio import Redis
from redis.exceptions import LockError, RedisError

logger = logging.getLogger(__name__)
_DEFAULT_MINIMUM_INTERVAL_SECONDS: Final = 1.05
_TOKEN_SAFETY_SECONDS: Final = 60
_KEY_PREFIX: Final = "auto-stock:kis"


@dataclass(frozen=True, slots=True)
class KisAccessToken:
    value: SecretStr
    expires_at: datetime

    def is_valid_at(self, now: datetime, *, safety_seconds: int) -> bool:
        return self.expires_at > now + timedelta(seconds=safety_seconds)


type KisTokenIssuer = Callable[[], Awaitable[KisAccessToken]]


@dataclass(frozen=True, slots=True)
class KisCoordinationConfig:
    minimum_interval_seconds: float = _DEFAULT_MINIMUM_INTERVAL_SECONDS
    token_lock_seconds: float = 45
    wait_timeout_seconds: float = 50
    poll_interval_seconds: float = 0.05
    token_safety_seconds: int = _TOKEN_SAFETY_SECONDS


class KisCoordinationFailure(StrEnum):
    UNAVAILABLE = "KIS coordination is unavailable"
    INVALID_URL = "Valkey URL is invalid"
    SHARED_CREDENTIAL_INVALID = "KIS shared token is invalid"
    CREDENTIAL_EXPIRES_TOO_SOON = "KIS token expires too soon to share"
    CREDENTIAL_STORE_FAILED = "KIS shared token could not be stored"
    AUTH_WAIT_TIMEOUT = "KIS token coordination timed out"
    REQUEST_WAIT_TIMEOUT = "KIS request coordination timed out"
    INVALID_RESPONSE = "Valkey returned an invalid coordination response"


@final
@dataclass(frozen=True, slots=True)
class KisCoordinationError(Exception):
    reason: KisCoordinationFailure

    @override
    def __str__(self) -> str:
        return self.reason.value


class KisRequestCoordinator(Protocol):
    async def token(self, issuer: KisTokenIssuer) -> SecretStr: ...

    async def wait_for_request_slot(self) -> None: ...

    async def close(self) -> None: ...


class _StoredToken(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: str = Field(min_length=1, repr=False)
    expires_at: datetime


def kis_coordination_scope(
    environment: str,
    app_key: SecretStr,
    app_secret: SecretStr,
) -> str:
    message = f"{environment}\0{app_key.get_secret_value()}".encode()
    return hmac.new(
        app_secret.get_secret_value().encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


@final
class InMemoryKisRequestCoordinator:
    def __init__(self, config: KisCoordinationConfig | None = None) -> None:
        self._config = config or KisCoordinationConfig()
        self._token: KisAccessToken | None = None
        self._token_lock = anyio.Lock()
        self._request_lock = anyio.Lock()
        self._last_request_at: float | None = None

    async def token(self, issuer: KisTokenIssuer) -> SecretStr:
        now = datetime.now(UTC)
        if self._token is not None and self._token.is_valid_at(
            now, safety_seconds=self._config.token_safety_seconds
        ):
            return self._token.value
        async with self._token_lock:
            now = datetime.now(UTC)
            if self._token is not None and self._token.is_valid_at(
                now, safety_seconds=self._config.token_safety_seconds
            ):
                return self._token.value
            self._token = await issuer()
            return self._token.value

    async def wait_for_request_slot(self) -> None:
        async with self._request_lock:
            now = anyio.current_time()
            if self._last_request_at is not None:
                wait_seconds = self._config.minimum_interval_seconds - (now - self._last_request_at)
                if wait_seconds > 0:
                    await anyio.sleep(wait_seconds)
            self._last_request_at = anyio.current_time()

    async def close(self) -> None:
        await anyio.lowlevel.checkpoint()


@final
class ValkeyKisRequestCoordinator:
    def __init__(
        self,
        client: Redis,
        scope: str,
        config: KisCoordinationConfig,
    ) -> None:
        self._client = client
        self._config = config
        self._token_key = f"{_KEY_PREFIX}:{scope}:token"
        self._token_lock_key = f"{_KEY_PREFIX}:{scope}:token-lock"
        self._request_gate_key = f"{_KEY_PREFIX}:{scope}:request-gate"
        self._token: KisAccessToken | None = None
        self._token_lock = anyio.Lock()
        self._request_lock = anyio.Lock()

    @classmethod
    def from_url(
        cls,
        valkey_url: str,
        scope: str,
        config: KisCoordinationConfig | None = None,
    ) -> ValkeyKisRequestCoordinator:
        parsed_url = urlsplit(valkey_url)
        if parsed_url.scheme not in {"redis", "valkey"} or parsed_url.hostname is None:
            raise KisCoordinationError(KisCoordinationFailure.INVALID_URL)
        database_path = parsed_url.path.removeprefix("/")
        client = Redis(
            host=parsed_url.hostname,
            port=parsed_url.port or 6379,
            db=int(database_path) if database_path else 0,
            username=unquote(parsed_url.username) if parsed_url.username else None,
            password=unquote(parsed_url.password) if parsed_url.password else None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        return cls(client, scope, config or KisCoordinationConfig())

    async def token(self, issuer: KisTokenIssuer) -> SecretStr:
        now = datetime.now(UTC)
        if self._token is not None and self._token.is_valid_at(
            now, safety_seconds=self._config.token_safety_seconds
        ):
            return self._token.value
        try:
            return await self._coordinated_token(issuer)
        except RedisError as error:
            raise KisCoordinationError(KisCoordinationFailure.UNAVAILABLE) from error

    async def _coordinated_token(self, issuer: KisTokenIssuer) -> SecretStr:
        async with self._token_lock:
            cached = await self._read_shared_token()
            if cached is not None:
                self._token = cached
                logger.info("KIS shared access token reused")
                return cached.value
            try:
                async with self._client.lock(
                    self._token_lock_key,
                    timeout=self._config.token_lock_seconds,
                    sleep=self._config.poll_interval_seconds,
                    blocking_timeout=self._config.wait_timeout_seconds,
                    thread_local=False,
                ):
                    cached = await self._read_shared_token()
                    if cached is not None:
                        self._token = cached
                        return cached.value
                    issued = await issuer()
                    await self._store_shared_token(issued)
                    self._token = issued
                    logger.info("KIS shared access token issued")
                    return issued.value
            except LockError as error:
                raise KisCoordinationError(KisCoordinationFailure.AUTH_WAIT_TIMEOUT) from error

    async def _read_shared_token(self) -> KisAccessToken | None:
        raw = await self._client.get(self._token_key)
        if raw is None:
            return None
        try:
            stored = _StoredToken.model_validate_json(raw)
        except ValidationError as error:
            raise KisCoordinationError(KisCoordinationFailure.SHARED_CREDENTIAL_INVALID) from error
        if stored.expires_at.tzinfo is None:
            raise KisCoordinationError(KisCoordinationFailure.SHARED_CREDENTIAL_INVALID)
        token = KisAccessToken(SecretStr(stored.access_token), stored.expires_at.astimezone(UTC))
        if token.is_valid_at(
            datetime.now(UTC),
            safety_seconds=self._config.token_safety_seconds,
        ):
            return token
        _ = await self._client.delete(self._token_key)
        return None

    async def _store_shared_token(self, token: KisAccessToken) -> None:
        ttl_seconds = int(
            (token.expires_at - datetime.now(UTC)).total_seconds()
            - self._config.token_safety_seconds
        )
        if ttl_seconds <= 0:
            raise KisCoordinationError(KisCoordinationFailure.CREDENTIAL_EXPIRES_TOO_SOON)
        stored = _StoredToken(
            access_token=token.value.get_secret_value(),
            expires_at=token.expires_at,
        )
        result = await self._client.set(
            self._token_key,
            stored.model_dump_json(),
            ex=ttl_seconds,
        )
        if not _set_succeeded(result=result):
            raise KisCoordinationError(KisCoordinationFailure.CREDENTIAL_STORE_FAILED)

    async def wait_for_request_slot(self) -> None:
        try:
            async with self._request_lock:
                await self._reserve_request_slot()
        except RedisError as error:
            raise KisCoordinationError(KisCoordinationFailure.UNAVAILABLE) from error

    async def _reserve_request_slot(self) -> None:
        deadline = anyio.current_time() + self._config.wait_timeout_seconds
        interval_milliseconds = max(
            1,
            round(self._config.minimum_interval_seconds * 1000),
        )
        while anyio.current_time() < deadline:
            result = await self._client.set(
                self._request_gate_key,
                secrets.token_hex(8),
                nx=True,
                px=interval_milliseconds,
            )
            if _set_succeeded(result=result):
                return
            await anyio.sleep(self._config.poll_interval_seconds)
        raise KisCoordinationError(KisCoordinationFailure.REQUEST_WAIT_TIMEOUT)

    async def close(self) -> None:
        await self._client.aclose()


def _set_succeeded(*, result: bool | str | bytes | None) -> bool:
    if result in (True, "OK", b"OK"):
        return True
    if result in (False, None):
        return False
    raise KisCoordinationError(KisCoordinationFailure.INVALID_RESPONSE)
