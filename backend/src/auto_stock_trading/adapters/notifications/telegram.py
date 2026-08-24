"""Telegram Bot API 전송 어댑터(ADR-0014).

**토큰이 URL 경로에 들어간다**(`/bot<token>/sendMessage`). 그래서 이 어댑터는 오류 문구와 로그에
URL을 절대 담지 않는다. KIS 어댑터가 헤더를 로그에서 제외하는 것과 같은 이유이며, 여기서는 경로
자체가 비밀이다.

시스템에서 처음으로 밖으로 내보내는 경로이므로, 응답 판정을 느슨하게 두지 않는다: HTTP 200이면서
본문 `ok=true`일 때만 성공이다.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final, final

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from auto_stock_trading.application.notifications.dispatch import DeliveryOutcome

_BASE_URL: Final = "https://api.telegram.org"
# 문서상 4096자로 알려져 있으나 공식 문서에서 해당 절을 확인하지 못했다(계약 §미실측 2).
# 상한을 넘지 않도록 보수적으로 자르고, 자른 사실을 본문에 남긴다.
_MAX_TEXT: Final = 3900
_TRUNCATION_MARKER: Final = "\n…(잘렸음)"
_ERROR_LIMIT: Final = 400


class _TelegramContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)


class TelegramParameters(_TelegramContract):
    retry_after: int | None = None


class TelegramResponse(_TelegramContract):
    """`sendMessage` 응답. 성공은 `ok=true`로만 판정한다."""

    ok: bool
    error_code: int | None = None
    description: str | None = None
    parameters: TelegramParameters | None = None


def _payload_error(payload: TelegramResponse, status: int) -> str:
    """오류 문구를 만든다. URL·토큰은 담지 않는다."""
    code = payload.error_code if payload.error_code is not None else status
    return f"{code} {payload.description or ''}".strip()[:_ERROR_LIMIT]


@final
class TelegramSender:
    """`sendMessage` 한 건을 보낸다. 재시도와 간격은 호출자(폴러)가 정한다."""

    def __init__(self, client: httpx2.AsyncClient, *, token: str, chat_id: str) -> None:
        self._client = client
        self._token = token
        self._chat_id = chat_id

    async def send(self, body: str) -> DeliveryOutcome:
        text = body if len(body) <= _MAX_TEXT else body[:_MAX_TEXT] + _TRUNCATION_MARKER
        try:
            response = await self._client.post(
                f"{_BASE_URL}/bot{self._token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
            )
        except httpx2.HTTPError as error:
            # 예외 문자열에 요청 URL이 들어갈 수 있으므로 타입 이름만 남긴다.
            return DeliveryOutcome(
                delivered=False,
                error=type(error).__name__,
                retry_after=None,
            )
        return self._outcome(response)

    def _outcome(self, response: httpx2.Response) -> DeliveryOutcome:
        try:
            payload = TelegramResponse.model_validate_json(response.content)
        except ValidationError:
            return DeliveryOutcome(
                delivered=False,
                error=f"{response.status_code} unparsable response",
                retry_after=None,
            )
        # 200에 ok=false가 오는 경우를 성공으로 보지 않는다.
        if response.status_code == HTTPStatus.OK and payload.ok:
            return DeliveryOutcome(delivered=True, error=None, retry_after=None)
        return DeliveryOutcome(
            delivered=False,
            error=_payload_error(payload, response.status_code),
            retry_after=None if payload.parameters is None else payload.parameters.retry_after,
        )

    async def close(self) -> None:
        await self._client.aclose()
