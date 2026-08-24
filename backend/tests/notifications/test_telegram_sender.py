"""Telegram 전송 어댑터(ADR-0014 결정 5·7).

**토큰이 URL 경로에 들어간다.** 그래서 오류 기록과 로그에 URL을 남기지 않는 것이 이 어댑터의 핵심
제약이다. 실제 호출은 봇 토큰이 없어 아직 못 했고, 여기서는 계약된 요청·응답 형태로 검증한다.
"""

from collections.abc import Callable
from typing import Final

import anyio
import httpx2

from auto_stock_trading.adapters.notifications.telegram import TelegramSender

_TOKEN: Final = "123456:AAHfake-token-value-not-real"  # noqa: S105 — 가짜 값이다
_CHAT_ID: Final = "-1001234567890"


type Handler = Callable[[httpx2.Request], httpx2.Response]


def _client(handler: Handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        timeout=httpx2.Timeout(5.0),
    )


def test_a_successful_send_posts_the_chat_id_and_text() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"ok": True, "result": {"message_id": 7}})

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            outcome = await sender.send("[주문] 005930 삼성전자 매수 2주")
        finally:
            await sender.close()

        assert outcome.delivered is True
        assert outcome.error is None
        (request,) = requests
        assert request.url.path == f"/bot{_TOKEN}/sendMessage"
        body = request.content.decode()
        assert _CHAT_ID in body
        assert "삼성전자" in body

    anyio.run(scenario)


def test_http_200_with_ok_false_is_not_a_success() -> None:
    """200에 `ok=false`가 오는 경우를 성공으로 보지 않는다(계약 §전송)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        _ = request
        return httpx2.Response(
            200,
            json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
        )

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            outcome = await sender.send("본문")
        finally:
            await sender.close()

        assert outcome.delivered is False
        assert outcome.error is not None
        assert "400" in outcome.error
        assert "chat not found" in outcome.error

    anyio.run(scenario)


def test_a_429_carries_the_retry_after_when_present() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        _ = request
        return httpx2.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 12",
                "parameters": {"retry_after": 12},
            },
        )

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            outcome = await sender.send("본문")
        finally:
            await sender.close()

        assert outcome.delivered is False
        assert outcome.retry_after == 12

    anyio.run(scenario)


def test_a_429_without_retry_after_still_reports_the_failure() -> None:
    """`retry_after`가 항상 온다고 단정하지 않는다(계약 §미실측 1)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        _ = request
        return httpx2.Response(429, json={"ok": False, "error_code": 429, "description": "slow"})

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            outcome = await sender.send("본문")
        finally:
            await sender.close()

        assert outcome.delivered is False
        assert outcome.retry_after is None
        assert outcome.error is not None

    anyio.run(scenario)


def test_the_error_never_contains_the_token_or_the_url() -> None:
    """토큰이 URL 경로에 있으므로 오류 문구에 URL을 담으면 비밀이 기록에 남는다."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        _ = request
        return httpx2.Response(
            401,
            json={"ok": False, "error_code": 401, "description": "Unauthorized"},
        )

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            outcome = await sender.send("본문")
        finally:
            await sender.close()

        assert outcome.error is not None
        assert _TOKEN not in outcome.error
        assert "api.telegram.org" not in outcome.error
        assert "http" not in outcome.error

    anyio.run(scenario)


def test_a_transport_error_is_reported_without_the_url() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        message = "connect timeout"
        raise httpx2.ConnectTimeout(message, request=request)

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            outcome = await sender.send("본문")
        finally:
            await sender.close()

        assert outcome.delivered is False
        assert outcome.error is not None
        assert _TOKEN not in outcome.error

    anyio.run(scenario)


def test_a_body_longer_than_the_limit_is_truncated_with_a_marker() -> None:
    """길이 상한은 미실측이다. 넘지 않도록 자르고 자른 사실을 남긴다(계약 §미실측 2)."""
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"ok": True})

    async def scenario() -> None:
        sender = TelegramSender(_client(handler), token=_TOKEN, chat_id=_CHAT_ID)
        try:
            _ = await sender.send("가" * 5000)
        finally:
            await sender.close()

        (request,) = requests
        text = request.content.decode()
        assert "잘렸음" in text

    anyio.run(scenario)
