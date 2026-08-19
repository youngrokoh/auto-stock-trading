"""모의투자 실시간 체결통보 리스너. 읽기 전용이며 주문을 제출·취소하지 않는다(ADR-0009)."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import anyio

from auto_stock_trading.adapters.brokers.kis_coordination import kis_coordination_scope
from auto_stock_trading.adapters.brokers.kis_coordination_valkey import (
    ValkeyKisRequestCoordinator,
)
from auto_stock_trading.adapters.brokers.kis_http import create_kis_http_client
from auto_stock_trading.adapters.brokers.kis_realtime import (
    PAPER_NOTIFICATION_TRANSACTION_ID,
    KisApprovalClient,
    KisNotificationSocket,
    RealtimeFrameError,
)
from auto_stock_trading.adapters.database.trading_notification_store import (
    HEARTBEAT_SECONDS,
    PostgresNotificationStore,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.application.trading.notifications import FillNotificationListener
from auto_stock_trading.domain.orders.account import account_reference
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import (
    load_kis_account,
    load_kis_credentials,
    load_kis_hts_id,
)

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

_PAPER_ONLY: Final = "the fill notification listener is allowed in the paper environment only"
_CLOSED: Final = "CONNECTION_CLOSED"
_FRAME_ERROR: Final = "FRAME_ERROR"
_STOPPED: Final = "STOPPED"
_BACKOFF_SECONDS: Final = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


class Arguments(argparse.Namespace):
    listen: bool = False
    status: bool = False
    max_sessions: int = 0


def _paper_settings() -> Settings:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        raise RuntimeError(_PAPER_ONLY)
    return settings


def _now() -> datetime:
    return datetime.now(UTC)


def _backoff(attempt: int) -> float:
    return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]


async def _heartbeat(listener: FillNotificationListener, session_id: UUID) -> None:
    """세션 심박. 제출 게이트가 이 값으로 부착을 판정한다."""
    while True:
        await anyio.sleep(HEARTBEAT_SECONDS)
        await listener.heartbeat(session_id, _now())


async def _session(
    listener: FillNotificationListener,
    socket: KisNotificationSocket,
    transaction_id: str,
) -> tuple[int, bool]:
    """한 세션을 수신한다. 반환은 처리한 통보 수와 차단 발생 여부다."""
    attach = await listener.attach(transaction_id, _now())
    handled = 0
    blocked = attach.blocked
    reason = _CLOSED
    try:
        async with anyio.create_task_group() as task_group:
            _ = task_group.start_soon(_heartbeat, listener, attach.session_id)
            async for payload in socket.stream():
                result = await listener.handle(payload, _now())
                handled += 1
                blocked = blocked or result.blocked
            task_group.cancel_scope.cancel()
    except RealtimeFrameError as error:
        reason = _FRAME_ERROR
        await listener.record_failure(error.detail, _now())
        logger.warning("KIS notification session failed: %s", error.detail)
    finally:
        await listener.detach(attach.session_id, reason, _now())
    return handled, blocked


async def listen(arguments: Arguments) -> str:
    settings = _paper_settings()
    database_url = settings.database_url.get_secret_value()
    credentials = load_kis_credentials(settings)
    account = load_kis_account(settings)
    hts_id = load_kis_hts_id(settings)
    store = PostgresTradingStore.from_url(database_url)
    notifications = PostgresNotificationStore.from_url(database_url)
    approvals = KisApprovalClient(
        client=create_kis_http_client(settings.kis_base_url),
        credentials=credentials,
        coordinator=ValkeyKisRequestCoordinator.from_url(
            settings.valkey_url.get_secret_value(),
            kis_coordination_scope(
                settings.kis_environment.value,
                credentials.app_key,
                credentials.app_secret,
            ),
        ),
    )
    socket = KisNotificationSocket(
        websocket_url=settings.kis_websocket_url,
        transaction_id=PAPER_NOTIFICATION_TRANSACTION_ID,
        hts_id=hts_id,
        approvals=approvals,
    )
    listener = FillNotificationListener(
        orders=store,
        notifications=notifications,
        environment=settings.kis_environment.value,
        account_reference=account_reference(
            account.number.get_secret_value(),
            account.product_code.get_secret_value(),
        ),
    )
    sessions = 0
    handled = 0
    blocked = False
    try:
        while arguments.max_sessions <= 0 or sessions < arguments.max_sessions:
            received, session_blocked = await _session(
                listener,
                socket,
                PAPER_NOTIFICATION_TRANSACTION_ID,
            )
            handled += received
            blocked = blocked or session_blocked
            sessions += 1
            if arguments.max_sessions > 0 and sessions >= arguments.max_sessions:
                break
            await anyio.sleep(_backoff(sessions - 1))
    finally:
        await approvals.close()
        await notifications.close()
        await store.close()
    return f"sessions={sessions} notifications={handled} blocked={blocked} reason={_STOPPED}"


async def status() -> str:
    settings = _paper_settings()
    notifications = PostgresNotificationStore.from_url(settings.database_url.get_secret_value())
    try:
        attached = await notifications.attached(settings.kis_environment.value, _now())
    finally:
        await notifications.close()
    return f"attached={attached} environment={settings.kis_environment.value}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="모의투자 실시간 체결통보 리스너 (실전 환경에서는 거부)",
    )
    _ = parser.add_argument("--listen", action="store_true")
    _ = parser.add_argument("--status", action="store_true")
    _ = parser.add_argument("--max-sessions", type=int, default=0)
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.status:
        print(anyio.run(status))  # noqa: T201
        return
    if arguments.listen:
        print(anyio.run(listen, arguments))  # noqa: T201
        return
    parser.error("--listen 또는 --status 중 하나가 필요하다")


if __name__ == "__main__":
    main()
