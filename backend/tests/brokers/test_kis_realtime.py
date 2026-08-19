from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Final, final

import anyio
import httpx2
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import BaseModel, RootModel, SecretStr

from auto_stock_trading.adapters.brokers.kis_coordination import (
    InMemoryKisRequestCoordinator,
    KisCoordinationConfig,
)
from auto_stock_trading.adapters.brokers.kis_http import KisCredentials
from auto_stock_trading.adapters.brokers.kis_realtime import (
    APPROVAL_ENDPOINT,
    PAPER_NOTIFICATION_TRANSACTION_ID,
    ControlFrame,
    DataFrame,
    KisApprovalClient,
    KisNotificationSocket,
    RealtimeFrameError,
    SubscriptionCredentials,
    classify_frame,
    decrypt_notification,
    subscribe_frame,
)

_KEY: Final = "0123456789abcdef0123456789abcdef"
_IV: Final = "abcdef0123456789"
_TR_KEY: Final = SecretStr("fixture-hts-id")
_APPROVAL_KEY: Final = "fixture-approval-key"
_URL: Final = "ws://ops.example.invalid:31000"
_PAYLOAD: Final = "***^***^0000012345^0000000000^02"
_PING: Final = '{"header":{"tr_id":"PINGPONG","datetime":"20260819103000"}}'
_FAST: Final = KisCoordinationConfig(minimum_interval_seconds=0.01)
_AES_BLOCK_BITS: Final = 128


class _SubscribeHeader(BaseModel):
    approval_key: str
    custtype: str
    tr_type: str


class _SubscribeInput(BaseModel):
    tr_id: str
    tr_key: str


class _SubscribeBody(BaseModel):
    input: _SubscribeInput


class _SubscribeFrame(BaseModel):
    """구독 프레임을 Any 없이 읽기 위한 테스트 전용 구조."""

    header: _SubscribeHeader
    body: _SubscribeBody


class _ApprovalBody(RootModel[dict[str, str]]):
    """접속키 발급 요청 본문 확인용."""


def _sent_frame(raw: str) -> _SubscribeFrame:
    return _SubscribeFrame.model_validate_json(raw)


def _encrypted(plaintext: str) -> str:
    padder = padding.PKCS7(_AES_BLOCK_BITS).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_KEY.encode()), modes.CBC(_IV.encode())).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def _data_frame(plaintext: str, *, encrypted: bool = True) -> str:
    flag = "1" if encrypted else "0"
    body = _encrypted(plaintext) if encrypted else plaintext
    return f"{flag}|{PAPER_NOTIFICATION_TRANSACTION_ID}|001|{body}"


def _subscribe_response(*, ok: bool = True) -> str:
    body: dict[str, object] = (
        {
            "rt_cd": "0",
            "msg_cd": "OPSP0000",
            "msg1": "SUBSCRIBE SUCCESS",
            "output": {"iv": _IV, "key": _KEY},
        }
        if ok
        else {"rt_cd": "1", "msg_cd": "OPSP0002", "msg1": "ALREADY IN SUBSCRIBE"}
    )
    return json.dumps(
        {
            "header": {"tr_id": PAPER_NOTIFICATION_TRANSACTION_ID, "tr_key": "masked"},
            "body": body,
        }
    )


@final
@dataclass
class FakeConnection:
    incoming: list[str]
    sent: list[str] = field(default_factory=list)
    closed: bool = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def receive(self) -> str:
        if not self.incoming:
            raise ConnectionResetError
        return self.incoming.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _socket(connection: FakeConnection, approvals: KisApprovalClient) -> KisNotificationSocket:
    async def connect(url: str) -> FakeConnection:
        assert url == _URL
        return connection

    return KisNotificationSocket(
        websocket_url=_URL,
        transaction_id=PAPER_NOTIFICATION_TRANSACTION_ID,
        hts_id=_TR_KEY,
        approvals=approvals,
        connect=connect,
    )


def _approvals(*, calls: list[httpx2.Request] | None = None) -> KisApprovalClient:
    recorded = calls if calls is not None else []

    def handler(request: httpx2.Request) -> httpx2.Response:
        recorded.append(request)
        if request.url.path != APPROVAL_ENDPOINT:
            return httpx2.Response(404, json={})
        return httpx2.Response(200, json={"approval_key": _APPROVAL_KEY})

    client = httpx2.AsyncClient(
        base_url="https://openapivts.example.invalid",
        transport=httpx2.MockTransport(handler),
    )
    return KisApprovalClient(
        client=client,
        credentials=KisCredentials(SecretStr("app-key"), SecretStr("app-secret")),
        coordinator=InMemoryKisRequestCoordinator(_FAST),
    )


def test_subscribe_frame_carries_the_approval_key_and_registration_type() -> None:
    frame = _sent_frame(
        subscribe_frame(
            approval_key=SecretStr(_APPROVAL_KEY),
            transaction_id=PAPER_NOTIFICATION_TRANSACTION_ID,
            tr_key=_TR_KEY,
            register=True,
        )
    )

    assert frame.header.approval_key == _APPROVAL_KEY
    assert frame.header.tr_type == "1"
    assert frame.header.custtype == "P"
    assert frame.body.input.tr_id == PAPER_NOTIFICATION_TRANSACTION_ID
    assert frame.body.input.tr_key == _TR_KEY.get_secret_value()


def test_unsubscribe_frame_uses_the_release_type() -> None:
    frame = _sent_frame(
        subscribe_frame(
            approval_key=SecretStr(_APPROVAL_KEY),
            transaction_id=PAPER_NOTIFICATION_TRANSACTION_ID,
            tr_key=_TR_KEY,
            register=False,
        )
    )

    assert frame.header.tr_type == "2"


def test_ping_frame_is_recognised_as_a_control_frame() -> None:
    frame = classify_frame(_PING)

    assert isinstance(frame, ControlFrame)
    assert frame.is_ping
    assert frame.credentials is None


def test_subscribe_success_frame_carries_the_encryption_material() -> None:
    frame = classify_frame(_subscribe_response())

    assert isinstance(frame, ControlFrame)
    assert not frame.is_ping
    assert frame.return_code == "0"
    assert frame.credentials == SubscriptionCredentials(key=_KEY, iv=_IV)


def test_subscribe_failure_frame_has_no_encryption_material() -> None:
    frame = classify_frame(_subscribe_response(ok=False))

    assert isinstance(frame, ControlFrame)
    assert frame.return_code == "1"
    assert frame.message_code == "OPSP0002"
    assert frame.credentials is None


def test_data_frame_is_split_into_its_four_tokens() -> None:
    frame = classify_frame(_data_frame(_PAYLOAD))

    assert isinstance(frame, DataFrame)
    assert frame.encrypted
    assert frame.transaction_id == PAPER_NOTIFICATION_TRANSACTION_ID
    assert frame.count == 1


@pytest.mark.parametrize(
    "raw",
    ["", "1|H0STCNI9|001", "9|H0STCNI9|001|body", "1|H0STCNI9|abc|body", "{not json"],
)
def test_unreadable_frames_fail_closed(raw: str) -> None:
    with pytest.raises(RealtimeFrameError):
        _ = classify_frame(raw)


def test_decryption_round_trip_returns_the_plaintext_body() -> None:
    frame = classify_frame(_data_frame(_PAYLOAD))
    assert isinstance(frame, DataFrame)

    decrypted = decrypt_notification(SubscriptionCredentials(key=_KEY, iv=_IV), frame.body)

    assert decrypted == _PAYLOAD


def test_decryption_of_a_corrupt_body_fails_closed() -> None:
    with pytest.raises(RealtimeFrameError):
        _ = decrypt_notification(SubscriptionCredentials(key=_KEY, iv=_IV), "not-base64!!")


def test_approval_key_is_issued_once_and_never_appears_in_the_request_path() -> None:
    async def run() -> None:
        calls: list[httpx2.Request] = []
        approvals = _approvals(calls=calls)

        first = await approvals.approval_key()
        second = await approvals.approval_key()
        await approvals.close()

        assert first.get_secret_value() == _APPROVAL_KEY
        assert second.get_secret_value() == _APPROVAL_KEY
        assert len(calls) == 1
        body = _ApprovalBody.model_validate_json(calls[0].content).root
        assert body["grant_type"] == "client_credentials"
        assert "secretkey" in body
        assert "appsecret" not in body
        assert _APPROVAL_KEY not in str(calls[0].url)

    anyio.run(run)


def test_stream_subscribes_answers_pings_and_yields_decrypted_bodies() -> None:
    async def run() -> None:
        connection = FakeConnection(
            incoming=[
                _subscribe_response(),
                _PING,
                _data_frame(_PAYLOAD),
                _data_frame("second^body^value"),
            ]
        )
        approvals = _approvals()
        received: list[str] = []

        try:
            received.extend([payload async for payload in _socket(connection, approvals).stream()])
        finally:
            await approvals.close()

        assert received == [_PAYLOAD, "second^body^value"]
        assert _sent_frame(connection.sent[0]).header.tr_type == "1"
        assert connection.sent[1] == _PING
        assert connection.closed

    anyio.run(run)


def test_stream_rejects_a_body_that_arrives_before_the_encryption_material() -> None:
    async def run() -> None:
        connection = FakeConnection(incoming=[_data_frame(_PAYLOAD)])
        approvals = _approvals()

        with pytest.raises(RealtimeFrameError):
            async for _ in _socket(connection, approvals).stream():
                pass
        await approvals.close()

    anyio.run(run)


def test_stream_rejects_a_plaintext_notification_frame() -> None:
    async def run() -> None:
        connection = FakeConnection(
            incoming=[_subscribe_response(), _data_frame(_PAYLOAD, encrypted=False)]
        )
        approvals = _approvals()

        with pytest.raises(RealtimeFrameError):
            async for _ in _socket(connection, approvals).stream():
                pass
        await approvals.close()

    anyio.run(run)


def test_stream_invalidates_the_approval_key_when_the_subscription_is_refused() -> None:
    async def run() -> None:
        connection = FakeConnection(incoming=[_subscribe_response(ok=False)])
        calls: list[httpx2.Request] = []
        approvals = _approvals(calls=calls)

        with pytest.raises(RealtimeFrameError):
            async for _ in _socket(connection, approvals).stream():
                pass

        second = await approvals.approval_key()
        await approvals.close()

        assert second.get_secret_value() == _APPROVAL_KEY
        assert len(calls) == 2

    anyio.run(run)


def test_stream_ends_when_the_connection_closes() -> None:
    async def run() -> None:
        connection = FakeConnection(incoming=[_subscribe_response()])
        approvals = _approvals()
        received: list[str] = []

        received = [payload async for payload in _socket(connection, approvals).stream()]
        await approvals.close()

        assert received == []
        assert connection.closed

    anyio.run(run)
