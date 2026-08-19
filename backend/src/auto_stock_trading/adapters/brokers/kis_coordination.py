"""KIS 자격증명·요청 조정의 공용 타입과 단일 프로세스 구현. Valkey 구현은 별도 모듈에 있다."""

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol, final, override

import anyio
import anyio.lowlevel
from pydantic import SecretStr

_DEFAULT_MINIMUM_INTERVAL_SECONDS: Final = 1.05
_TOKEN_SAFETY_SECONDS: Final = 60
_APPROVAL_TTL_SECONDS: Final = 21600
KIS_KEY_PREFIX: Final = "auto-stock:kis"


@dataclass(frozen=True, slots=True)
class KisAccessToken:
    value: SecretStr
    expires_at: datetime

    def is_valid_at(self, now: datetime, *, safety_seconds: int) -> bool:
        return self.expires_at > now + timedelta(seconds=safety_seconds)


type KisTokenIssuer = Callable[[], Awaitable[KisAccessToken]]
type KisApprovalIssuer = Callable[[], Awaitable[SecretStr]]


@dataclass(frozen=True, slots=True)
class KisCoordinationConfig:
    minimum_interval_seconds: float = _DEFAULT_MINIMUM_INTERVAL_SECONDS
    token_lock_seconds: float = 45
    wait_timeout_seconds: float = 50
    poll_interval_seconds: float = 0.05
    token_safety_seconds: int = _TOKEN_SAFETY_SECONDS
    # 웹소켓 접속키 발급 응답은 만료 시각을 주지 않는다. KIS 문서의 24시간보다 짧은 우리 쪽
    # 보수적 수명만 쓰고, 구독이 거부되면 캐시를 버리고 재발급한다.
    approval_ttl_seconds: int = _APPROVAL_TTL_SECONDS


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


class KisApprovalCoordinator(Protocol):
    """웹소켓 접속키 공유. 접근토큰과 별개의 자격증명이므로 별도 프로토콜로 둔다."""

    async def approval_key(self, issuer: KisApprovalIssuer) -> SecretStr: ...

    async def invalidate_approval_key(self) -> None: ...

    async def wait_for_request_slot(self) -> None: ...

    async def close(self) -> None: ...


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
        self._approval_key: SecretStr | None = None
        self._token_lock = anyio.Lock()
        self._approval_lock = anyio.Lock()
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

    async def approval_key(self, issuer: KisApprovalIssuer) -> SecretStr:
        if self._approval_key is not None:
            return self._approval_key
        async with self._approval_lock:
            if self._approval_key is not None:
                return self._approval_key
            self._approval_key = await issuer()
            return self._approval_key

    async def invalidate_approval_key(self) -> None:
        async with self._approval_lock:
            self._approval_key = None

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
