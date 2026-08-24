"""외부 알림 폴러 CLI(ADR-0014).

`--dispatch`는 한 번 투영하고 미발신 건을 보낸다. `--status`는 발신 현황만 출력한다. 자격증명이
없으면 전송을 시도하지 않고 그 사실을 출력한다 — 워터마크도 옮기지 않는다.

**토큰과 chat_id는 출력하지 않는다.** 토큰은 URL 경로에 들어가므로 URL도 출력하지 않는다.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import anyio
import httpx2

from auto_stock_trading.adapters.database.notification_store import (
    PostgresNotificationOutboxStore,
)
from auto_stock_trading.adapters.notifications.telegram import TelegramSender
from auto_stock_trading.application.notifications.dispatch import (
    NotificationDispatcher,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import SecretStr

_TIMEOUT_SECONDS: Final = 10.0
_NO_CREDENTIALS: Final = "자격증명이 없어 전송하지 않았다(봇 토큰·chat_id secret 미설정)"


class Arguments(argparse.Namespace):
    dispatch: bool = False
    status: bool = False


def _secret(direct: SecretStr | None, file_path: Path | None) -> str | None:
    """직접 값 또는 secret 파일. 없으면 None이며 값을 메시지에 넣지 않는다."""
    if direct is not None and direct.get_secret_value():
        return direct.get_secret_value()
    if file_path is None:
        return None
    try:
        value = file_path.read_text(encoding="utf-8").strip()
    except OSError, UnicodeError:
        return None
    return value or None


def _sender(settings: Settings) -> TelegramSender | None:
    token = _secret(settings.telegram_bot_token, settings.telegram_bot_token_file)
    chat_id = _secret(settings.telegram_chat_id, settings.telegram_chat_id_file)
    if token is None or chat_id is None:
        return None
    client = httpx2.AsyncClient(timeout=httpx2.Timeout(_TIMEOUT_SECONDS))
    return TelegramSender(client, token=token, chat_id=chat_id)


async def dispatch_notifications() -> str:
    settings = Settings()
    store = PostgresNotificationOutboxStore.from_url(
        settings.database_url.get_secret_value(),
    )
    sender = _sender(settings)
    dispatcher = NotificationDispatcher(
        store=store,
        sender=sender,
        environment=settings.kis_environment.value,
        poll_cap=settings.notification_poll_cap,
    )
    try:
        summary = await dispatcher.dispatch(datetime.now(UTC))
    finally:
        if sender is not None:
            await sender.close()
        await store.close()
    if summary.reason is not None:
        return _NO_CREDENTIALS
    return (
        f"projected={summary.projected} sent={summary.sent} "
        f"failed={summary.failed} summarized={summary.summarized}"
    )


async def notification_status() -> str:
    settings = Settings()
    store = PostgresNotificationOutboxStore.from_url(
        settings.database_url.get_secret_value(),
    )
    try:
        pending, failed, sent, oldest = await store.counts(settings.kis_environment.value)
    finally:
        await store.close()
    configured = _sender(settings) is not None
    oldest_text = "-" if oldest is None else oldest.isoformat()
    return (
        f"pending={pending} failed={failed} sent={sent} "
        f"oldest_pending={oldest_text} credentials={'yes' if configured else 'no'}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="주문·위험 이벤트 외부 알림 폴러")
    _ = parser.add_argument("--dispatch", action="store_true")
    _ = parser.add_argument("--status", action="store_true")
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.dispatch:
        print(anyio.run(dispatch_notifications))  # noqa: T201
        return
    if arguments.status:
        print(anyio.run(notification_status))  # noqa: T201
        return
    parser.error("--dispatch 또는 --status 중 하나가 필요하다")


if __name__ == "__main__":
    main()
