"""Valkey 기반 KIS 조정 구현. 장애 시 자체 발급으로 우회하지 않는다(ADR-0005)."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, final
from urllib.parse import unquote, urlsplit

import anyio
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from redis.asyncio import Redis
from redis.exceptions import LockError, RedisError

from auto_stock_trading.adapters.brokers.kis_coordination import (
    KIS_KEY_PREFIX,
    KisAccessToken,
    KisCoordinationConfig,
    KisCoordinationError,
    KisCoordinationFailure,
)

if TYPE_CHECKING:
    from auto_stock_trading.adapters.brokers.kis_coordination import (
        KisApprovalIssuer,
        KisTokenIssuer,
    )

logger = logging.getLogger(__name__)


class _StoredToken(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: str = Field(min_length=1, repr=False)
    expires_at: datetime


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
        self._token_key = f"{KIS_KEY_PREFIX}:{scope}:token"
        self._token_lock_key = f"{KIS_KEY_PREFIX}:{scope}:token-lock"
        self._approval_key_name = f"{KIS_KEY_PREFIX}:{scope}:approval"
        self._approval_lock_key = f"{KIS_KEY_PREFIX}:{scope}:approval-lock"
        self._request_gate_key = f"{KIS_KEY_PREFIX}:{scope}:request-gate"
        self._token: KisAccessToken | None = None
        self._approval: SecretStr | None = None
        self._token_lock = anyio.Lock()
        self._approval_lock = anyio.Lock()
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

    async def approval_key(self, issuer: KisApprovalIssuer) -> SecretStr:
        """웹소켓 접속키를 환경·자격증명 범위 안에서 공유한다."""
        if self._approval is not None:
            return self._approval
        try:
            return await self._coordinated_approval_key(issuer)
        except RedisError as error:
            raise KisCoordinationError(KisCoordinationFailure.UNAVAILABLE) from error

    async def invalidate_approval_key(self) -> None:
        """구독이 거부되면 공유 접속키를 버린다. 다음 호출이 재발급한다."""
        async with self._approval_lock:
            self._approval = None
            try:
                _ = await self._client.delete(self._approval_key_name)
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

    async def _coordinated_approval_key(self, issuer: KisApprovalIssuer) -> SecretStr:
        async with self._approval_lock:
            cached = _decoded(await self._client.get(self._approval_key_name))
            if cached is not None:
                self._approval = SecretStr(cached)
                logger.info("KIS shared websocket approval key reused")
                return self._approval
            try:
                async with self._client.lock(
                    self._approval_lock_key,
                    timeout=self._config.token_lock_seconds,
                    sleep=self._config.poll_interval_seconds,
                    blocking_timeout=self._config.wait_timeout_seconds,
                    thread_local=False,
                ):
                    cached = _decoded(await self._client.get(self._approval_key_name))
                    if cached is not None:
                        self._approval = SecretStr(cached)
                        return self._approval
                    issued = await issuer()
                    await self._store_shared_approval_key(issued)
                    self._approval = issued
                    logger.info("KIS shared websocket approval key issued")
                    return issued
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

    async def _store_shared_approval_key(self, approval_key: SecretStr) -> None:
        result = await self._client.set(
            self._approval_key_name,
            approval_key.get_secret_value(),
            ex=self._config.approval_ttl_seconds,
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


def _decoded(raw: bytes | str | None) -> str | None:
    """`decode_responses`가 켜져 있어도 타입은 bytes를 허용하므로 여기서 좁힌다."""
    if raw is None:
        return None
    value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return value or None


def _set_succeeded(*, result: bool | str | bytes | None) -> bool:
    if result in (True, "OK", b"OK"):
        return True
    if result in (False, None):
        return False
    raise KisCoordinationError(KisCoordinationFailure.INVALID_RESPONSE)
