"""KIS 실시간 체결통보 웹소켓 경계. 읽기 전용이며 주문 쓰기 API를 호출하지 않는다."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, final, override

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import WebSocketException

from auto_stock_trading.adapters.brokers.kis_http import KisTransportError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    import httpx2

    from auto_stock_trading.adapters.brokers.kis_coordination import KisApprovalCoordinator
    from auto_stock_trading.adapters.brokers.kis_http import KisCredentials

logger = logging.getLogger(__name__)

APPROVAL_ENDPOINT: Final = "/oauth2/Approval"
PAPER_NOTIFICATION_WEBSOCKET_URL: Final = "ws://ops.koreainvestment.com:31000"
PAPER_NOTIFICATION_TRANSACTION_ID: Final = "H0STCNI9"
_PING_TRANSACTION_ID: Final = "PINGPONG"
_REGISTER: Final = "1"
_RELEASE: Final = "2"
_DATA_TOKENS: Final = 4
_ENCRYPTED_FLAGS: Final = frozenset({"0", "1"})
_AES_KEY_BYTES: Final = 32
_AES_IV_BYTES: Final = 16
_AES_BLOCK_BITS: Final = 128
_SUCCESS: Final = "0"
_HTTP_ERROR_STATUS: Final = 400


@final
@dataclass(frozen=True, slots=True)
class RealtimeFrameError(Exception):
    """계약과 다른 프레임. 체결을 놓쳤을 수 있으므로 추정하지 않는다."""

    detail: str

    @override
    def __str__(self) -> str:
        return f"realtime frame does not match the contract: {self.detail}"


@dataclass(frozen=True, slots=True)
class SubscriptionCredentials:
    """구독 성공 응답이 주는 AES 키와 IV. 로그에 남기지 않는다."""

    key: str
    iv: str


@dataclass(frozen=True, slots=True)
class ControlFrame:
    transaction_id: str
    is_ping: bool
    return_code: str | None
    message_code: str | None
    message: str | None
    credentials: SubscriptionCredentials | None


@dataclass(frozen=True, slots=True)
class DataFrame:
    encrypted: bool
    transaction_id: str
    count: int
    body: str


class _Output(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    key: str = Field(min_length=1, repr=False)
    iv: str = Field(min_length=1, repr=False)


class _Body(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    rt_cd: str | None = None
    msg_cd: str | None = None
    msg1: str | None = None
    output: _Output | None = None


class _Header(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    tr_id: str = Field(min_length=1)


class _ControlPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    header: _Header
    body: _Body | None = None


class _ApprovalResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    approval_key: str = Field(min_length=1, repr=False)


def subscribe_frame(
    *,
    approval_key: SecretStr,
    transaction_id: str,
    tr_key: SecretStr,
    register: bool,
) -> str:
    """구독 등록·해제 프레임. `tr_key`는 모의투자 HTS ID다."""
    return json.dumps(
        {
            "header": {
                "approval_key": approval_key.get_secret_value(),
                "custtype": "P",
                "tr_type": _REGISTER if register else _RELEASE,
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": transaction_id, "tr_key": tr_key.get_secret_value()}},
        }
    )


def _control_frame(raw: str) -> ControlFrame:
    try:
        payload = _ControlPayload.model_validate_json(raw)
    except ValidationError as error:
        detail = "control frame is not the documented JSON shape"
        raise RealtimeFrameError(detail) from error
    body = payload.body
    output = None if body is None else body.output
    return ControlFrame(
        transaction_id=payload.header.tr_id,
        is_ping=payload.header.tr_id == _PING_TRANSACTION_ID,
        return_code=None if body is None else body.rt_cd,
        message_code=None if body is None else body.msg_cd,
        message=None if body is None else body.msg1,
        credentials=(
            None if output is None else SubscriptionCredentials(key=output.key, iv=output.iv)
        ),
    )


def _data_frame(raw: str) -> DataFrame:
    tokens = raw.split("|")
    if len(tokens) != _DATA_TOKENS:
        detail = f"data frame has {len(tokens)} tokens instead of {_DATA_TOKENS}"
        raise RealtimeFrameError(detail)
    flag, transaction_id, count, body = tokens
    if flag not in _ENCRYPTED_FLAGS:
        detail = "encryption flag is unknown"
        raise RealtimeFrameError(detail)
    if not count.isdigit():
        detail = "record count is not numeric"
        raise RealtimeFrameError(detail)
    if not body:
        detail = "data frame body is empty"
        raise RealtimeFrameError(detail)
    return DataFrame(
        encrypted=flag == "1",
        transaction_id=transaction_id,
        count=int(count),
        body=body,
    )


def classify_frame(raw: str) -> ControlFrame | DataFrame:
    """제어 메시지와 데이터 프레임을 첫 글자로 가른다."""
    if not raw:
        detail = "frame is empty"
        raise RealtimeFrameError(detail)
    if raw.startswith("{"):
        return _control_frame(raw)
    return _data_frame(raw)


def decrypt_notification(credentials: SubscriptionCredentials, body: str) -> str:
    """AES-256-CBC 복호화. 실패는 fail-closed이며 키·원문을 로그에 남기지 않는다."""
    key = credentials.key.encode("utf-8")
    iv = credentials.iv.encode("utf-8")
    if len(key) != _AES_KEY_BYTES or len(iv) != _AES_IV_BYTES:
        detail = "encryption material does not have the documented length"
        raise RealtimeFrameError(detail)
    try:
        ciphertext = base64.b64decode(body, validate=True)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(_AES_BLOCK_BITS).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        return plaintext.decode("utf-8")
    except (binascii.Error, ValueError, InvalidTag, UnicodeDecodeError) as error:
        detail = "notification body could not be decrypted"
        raise RealtimeFrameError(detail) from error


@final
@dataclass(frozen=True, slots=True)
class KisApprovalClient:
    """웹소켓 접속키 발급. 본문의 비밀 필드명은 `secretkey`이며 접근토큰과 별개다."""

    client: httpx2.AsyncClient
    credentials: KisCredentials
    coordinator: KisApprovalCoordinator

    async def approval_key(self) -> SecretStr:
        return await self.coordinator.approval_key(self._issue)

    async def invalidate(self) -> None:
        await self.coordinator.invalidate_approval_key()

    async def close(self) -> None:
        try:
            await self.client.aclose()
        finally:
            await self.coordinator.close()

    async def _issue(self) -> SecretStr:
        await self.coordinator.wait_for_request_slot()
        response = await self.client.post(
            APPROVAL_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "appkey": self.credentials.app_key.get_secret_value(),
                "secretkey": self.credentials.app_secret.get_secret_value(),
            },
        )
        if response.status_code >= _HTTP_ERROR_STATUS:
            raise KisTransportError(APPROVAL_ENDPOINT, response.status_code)
        try:
            issued = _ApprovalResponse.model_validate_json(response.text)
        except ValidationError as error:
            raise KisTransportError(APPROVAL_ENDPOINT, response.status_code) from error
        logger.info("KIS websocket approval key issued")
        return SecretStr(issued.approval_key)


class RealtimeConnection(Protocol):
    """웹소켓 한 연결. 테스트는 같은 모양의 대역을 넘긴다."""

    async def send(self, message: str) -> None: ...

    async def receive(self) -> str: ...

    async def aclose(self) -> None: ...


type ConnectionFactory = Callable[[str], Awaitable[RealtimeConnection]]


@final
class _WebsocketConnection:
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    async def send(self, message: str) -> None:
        await self._connection.send(message)

    async def receive(self) -> str:
        message = await self._connection.recv()
        if isinstance(message, bytes):
            return message.decode("utf-8")
        return message

    async def aclose(self) -> None:
        await self._connection.close()


async def open_kis_websocket(url: str) -> RealtimeConnection:
    """KIS 규격대로 자동 ping을 끈다. 연결 유지는 서버의 PINGPONG에 응답해 수행한다."""
    connection = await websocket_connect(url, ping_interval=None, open_timeout=10)
    return _WebsocketConnection(connection)


@final
class KisNotificationSocket:
    def __init__(
        self,
        *,
        websocket_url: str,
        transaction_id: str,
        hts_id: SecretStr,
        approvals: KisApprovalClient,
        connect: ConnectionFactory = open_kis_websocket,
    ) -> None:
        self._websocket_url = websocket_url
        self._transaction_id = transaction_id
        self._hts_id = hts_id
        self._approvals = approvals
        self._connect = connect

    async def stream(self) -> AsyncIterator[str]:
        """한 세션을 구독하고 복호화된 통보 본문을 순서대로 낸다. 끊기면 조용히 끝난다."""
        approval_key = await self._approvals.approval_key()
        connection = await self._connect(self._websocket_url)
        credentials: SubscriptionCredentials | None = None
        try:
            await connection.send(
                subscribe_frame(
                    approval_key=approval_key,
                    transaction_id=self._transaction_id,
                    tr_key=self._hts_id,
                    register=True,
                )
            )
            while True:
                try:
                    raw = await connection.receive()
                except OSError, WebSocketException:
                    logger.info("KIS notification socket closed")
                    return
                frame = classify_frame(raw)
                if isinstance(frame, ControlFrame):
                    credentials = await self._control(frame, connection, raw, credentials)
                    continue
                yield self._body(frame, credentials)
        finally:
            await connection.aclose()

    async def _control(
        self,
        frame: ControlFrame,
        connection: RealtimeConnection,
        raw: str,
        credentials: SubscriptionCredentials | None,
    ) -> SubscriptionCredentials | None:
        if frame.is_ping:
            await connection.send(raw)
            return credentials
        if frame.transaction_id != self._transaction_id:
            detail = "control frame reports another transaction id"
            raise RealtimeFrameError(detail)
        if frame.return_code != _SUCCESS or frame.credentials is None:
            await self._approvals.invalidate()
            detail = f"subscription was refused with {frame.message_code}"
            raise RealtimeFrameError(detail)
        logger.info("KIS notification subscription established")
        return frame.credentials

    def _body(self, frame: DataFrame, credentials: SubscriptionCredentials | None) -> str:
        if frame.transaction_id != self._transaction_id:
            detail = "data frame reports another transaction id"
            raise RealtimeFrameError(detail)
        if not frame.encrypted:
            detail = "notification arrived unencrypted"
            raise RealtimeFrameError(detail)
        if credentials is None:
            detail = "notification arrived before the encryption material"
            raise RealtimeFrameError(detail)
        return decrypt_notification(credentials, frame.body)
