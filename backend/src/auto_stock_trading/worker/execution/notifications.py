"""모의투자 실시간 체결통보 리스너. 읽기 전용이며 주문을 제출·취소하지 않는다(ADR-0009)."""

from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, final

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
from auto_stock_trading.application.trading.notifications import (
    AttachResult,
    FillNotificationListener,
    HandleResult,
    NotificationReplay,
)
from auto_stock_trading.domain.orders.account import account_reference
from auto_stock_trading.settings.runtime import KisEnvironment, Settings
from auto_stock_trading.worker.kis_credentials import (
    load_kis_account,
    load_kis_credentials,
    load_kis_hts_id,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

logger = logging.getLogger(__name__)

_PAPER_ONLY: Final = "the fill notification listener is allowed in the paper environment only"
_CLOSED: Final = "CONNECTION_CLOSED"
_FRAME_ERROR: Final = "FRAME_ERROR"
_STOPPED: Final = "STOPPED"
_BACKOFF_SECONDS: Final = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


class SessionListener(Protocol):
    """세션 한 번에 필요한 리스너 동작. 테스트는 같은 모양의 대역을 넘긴다."""

    async def attach(self, transaction_id: str, now: datetime) -> AttachResult: ...

    async def handle(self, payload: str, received_at: datetime) -> HandleResult: ...

    async def heartbeat(self, session_id: UUID, now: datetime) -> None: ...

    async def record_failure(self, detail: str, now: datetime) -> None: ...

    async def detach(self, session_id: UUID, reason: str, now: datetime) -> None: ...


class NotificationStream(Protocol):
    def stream(self) -> AsyncIterator[str]: ...


class Arguments(argparse.Namespace):
    listen: bool = False
    status: bool = False
    replay: bool = False
    max_sessions: int = 0


def _paper_settings() -> Settings:
    settings = Settings()
    if settings.kis_environment is not KisEnvironment.PAPER:
        raise RuntimeError(_PAPER_ONLY)
    return settings


def _now() -> datetime:
    return datetime.now(UTC)


def backoff_seconds(attempt: int) -> float:
    """계약의 재연결 대기(1·2·4·8·16·30초, 상한 30초)."""
    return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]


# 정상으로 볼 세션 길이. 이보다 짧고 통보도 없이 끝났으면 연결 자체가 서지 않은 것으로 본다.
HEALTHY_SESSION_SECONDS: Final = 60.0


def session_was_healthy(notifications: int, duration_seconds: float) -> bool:
    """이 세션이 성립했는지. 프레임을 받았거나 충분히 오래 붙어 있었으면 성립이다.

    통보가 없는 조용한 장도 정상이므로 길이만으로도 판정한다.
    """
    return notifications > 0 or duration_seconds >= HEALTHY_SESSION_SECONDS


@final
class ReconnectStreak:
    """연속 실패 횟수. 누적 세션 수가 아니다.

    백오프는 정의상 연속 실패에 증가하고 성공에 초기화된다. 누적 세션 수로 세면 오래 잘 돌수록
    재접속이 느려지고, 수열의 앞 값들이 의미를 잃는다 — 2026-08-27 실측에서 매시 정각 단절이
    2→4→8→30초로 자라 하루 뒤에는 항상 상한이었다. 한 시간 정상 수신한 세션은 실패가 아니다.
    """

    def __init__(self) -> None:
        self._failures = 0

    def record(self, *, healthy: bool) -> None:
        self._failures = 0 if healthy else self._failures + 1

    def wait_seconds(self) -> float:
        return backoff_seconds(self._failures)


async def _heartbeat(listener: SessionListener, session_id: UUID) -> None:
    """세션 심박. 제출 게이트가 이 값으로 부착을 판정한다."""
    while True:
        await anyio.sleep(HEARTBEAT_SECONDS)
        await listener.heartbeat(session_id, _now())


def is_interrupt(error: BaseException) -> bool:
    """운영자 중단만 정상 종료로 본다. 태스크 그룹은 예외를 묶어 올린다."""
    if isinstance(error, KeyboardInterrupt):
        return True
    if isinstance(error, BaseExceptionGroup):
        return all(is_interrupt(inner) for inner in error.exceptions)
    return False


@dataclass(slots=True)
class SessionTotals:
    """운영자에게 보고할 집계. 취소로 세션이 끝나도 값을 잃지 않게 밖에 둔다."""

    sessions: int = 0
    notifications: int = 0
    blocked: bool = False


async def run_session(
    listener: SessionListener,
    socket: NotificationStream,
    transaction_id: str,
    totals: SessionTotals,
) -> None:
    """한 세션을 수신하고 집계를 갱신한다."""
    attach = await listener.attach(transaction_id, _now())
    totals.blocked = totals.blocked or attach.blocked
    reason = _CLOSED
    try:
        async with anyio.create_task_group() as task_group:
            _ = task_group.start_soon(_heartbeat, listener, attach.session_id)
            # 프레임 오류는 이 프레임에서 처리해 태스크 그룹이 묶지 않게 한다. 묶이면
            # 예외 그룹이 되어 세션 재연결 대신 프로세스가 죽는다.
            try:
                async for payload in socket.stream():
                    result = await listener.handle(payload, _now())
                    totals.notifications += 1
                    totals.blocked = totals.blocked or result.blocked
            except RealtimeFrameError as error:
                reason = _FRAME_ERROR
                await listener.record_failure(error.detail, _now())
                logger.warning("KIS notification session failed: %s", error.detail)
            finally:
                task_group.cancel_scope.cancel()
    except* KeyboardInterrupt, SystemExit, anyio.get_cancelled_exc_class():
        # 운영자가 멈춘 것과 연결이 끊긴 것은 감사 로그에서 구분한다.
        reason = _STOPPED
        raise
    finally:
        # 취소 중에도 세션을 닫아야 다음 기동이 남은 연결 세션을 만나지 않는다.
        with anyio.CancelScope(shield=True):
            await listener.detach(attach.session_id, reason, _now())
        totals.sessions += 1


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
    try:
        state = await listener.reset_on_start(_now())
        logger.info("KIS notification listener starting with automation %s", state.value)
        return await run_sessions(listener, socket, arguments.max_sessions)
    finally:
        await approvals.close()
        await notifications.close()
        await store.close()


async def run_sessions(
    listener: SessionListener,
    socket: NotificationStream,
    max_sessions: int,
) -> str:
    """세션을 이어 붙인다. SIGINT·SIGTERM은 세션을 정상 종료로 닫고 루프를 끝낸다."""
    totals = SessionTotals()
    streak = ReconnectStreak()
    async with anyio.create_task_group() as task_group:
        _ = task_group.start_soon(_watch_signals, task_group.cancel_scope)
        while max_sessions <= 0 or totals.sessions < max_sessions:
            before = totals.notifications
            started = _now()
            await run_session(
                listener,
                socket,
                PAPER_NOTIFICATION_TRANSACTION_ID,
                totals,
            )
            streak.record(
                healthy=session_was_healthy(
                    totals.notifications - before,
                    (_now() - started).total_seconds(),
                )
            )
            if max_sessions > 0 and totals.sessions >= max_sessions:
                break
            await anyio.sleep(streak.wait_seconds())
        task_group.cancel_scope.cancel()
    return (
        f"sessions={totals.sessions} notifications={totals.notifications} "
        f"blocked={totals.blocked} reason={_STOPPED}"
    )


async def _watch_signals(scope: anyio.CancelScope) -> None:
    """컨테이너 정지(SIGTERM)와 Ctrl-C(SIGINT)를 같은 종료 경로로 모은다."""
    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for received in signals:
            logger.info("KIS notification listener stopping on signal %d", received)
            scope.cancel()
            return


async def replay() -> str:
    """대조 실패로 반영되지 않은 저장된 통보를 다시 반영한다. 증권사 호출은 없다."""
    settings = _paper_settings()
    notifications = PostgresNotificationStore.from_url(settings.database_url.get_secret_value())
    try:
        summary = await NotificationReplay(
            store=notifications,
            environment=settings.kis_environment.value,
        ).replay(_now())
    finally:
        await notifications.close()
    return (
        f"applied={summary.applied} unresolved={summary.unresolved} unreadable={summary.unreadable}"
    )


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
    _ = parser.add_argument("--replay", action="store_true")
    _ = parser.add_argument("--max-sessions", type=int, default=0)
    arguments = parser.parse_args(namespace=Arguments())
    if arguments.status:
        print(anyio.run(status))  # noqa: T201
        return
    if arguments.replay:
        print(anyio.run(replay))  # noqa: T201
        return
    if arguments.listen:
        try:
            print(anyio.run(listen, arguments))  # noqa: T201
        except (KeyboardInterrupt, BaseExceptionGroup) as error:
            if not is_interrupt(error):
                raise
            print("stopped=interrupt")  # noqa: T201
        return
    parser.error("--listen, --status, --replay 중 하나가 필요하다")


if __name__ == "__main__":
    main()
