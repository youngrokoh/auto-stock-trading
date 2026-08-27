from __future__ import annotations

import os
import signal
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, final
from uuid import UUID

import anyio
import pytest

from auto_stock_trading.adapters.brokers.kis_realtime import RealtimeFrameError
from auto_stock_trading.application.trading.notifications import AttachResult, HandleResult
from auto_stock_trading.worker.execution import notifications as worker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

_SESSION_ID: Final = UUID("22222222-2222-2222-2222-222222222222")
_TRANSACTION_ID: Final = "H0STCNI9"


@final
@dataclass
class FakeListener:
    payloads: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    detached: list[tuple[UUID, str]] = field(default_factory=list)
    blocked_on_attach: bool = False

    async def attach(self, transaction_id: str, now: datetime) -> AttachResult:
        assert transaction_id == _TRANSACTION_ID
        assert now is not None
        return AttachResult(session_id=_SESSION_ID, blocked=self.blocked_on_attach)

    async def handle(self, payload: str, received_at: datetime) -> HandleResult:
        assert received_at is not None
        self.payloads.append(payload)
        return HandleResult(outcomes=(), blocked=False)

    async def heartbeat(self, session_id: UUID, now: datetime) -> None:
        assert session_id == _SESSION_ID
        assert now is not None

    async def record_failure(self, detail: str, now: datetime) -> None:
        assert now is not None
        self.failures.append(detail)

    async def detach(self, session_id: UUID, reason: str, now: datetime) -> None:
        assert now is not None
        self.detached.append((session_id, reason))


@final
@dataclass
class FakeSocket:
    payloads: tuple[str, ...] = ()
    error: BaseException | None = None

    async def stream(self) -> AsyncIterator[str]:
        for payload in self.payloads:
            yield payload
        if self.error is not None:
            raise self.error


def test_a_closed_connection_is_recorded_as_a_connection_close() -> None:
    async def run() -> None:
        listener = FakeListener()
        socket = FakeSocket(payloads=("first^body", "second^body"))
        totals = worker.SessionTotals()

        await worker.run_session(listener, socket, _TRANSACTION_ID, totals)

        assert totals.notifications == 2
        assert not totals.blocked
        assert listener.payloads == ["first^body", "second^body"]
        assert listener.detached == [(_SESSION_ID, "CONNECTION_CLOSED")]

    anyio.run(run)


def test_a_frame_error_is_recorded_as_a_frame_error_and_does_not_escape() -> None:
    async def run() -> None:
        listener = FakeListener()
        socket = FakeSocket(error=RealtimeFrameError("body is empty"))

        await worker.run_session(listener, socket, _TRANSACTION_ID, worker.SessionTotals())

        assert listener.failures == ["body is empty"]
        assert listener.detached == [(_SESSION_ID, "FRAME_ERROR")]

    anyio.run(run)


def test_a_gap_at_attach_time_is_reported_as_blocked() -> None:
    async def run() -> None:
        listener = FakeListener(blocked_on_attach=True)
        totals = worker.SessionTotals()

        await worker.run_session(listener, FakeSocket(), _TRANSACTION_ID, totals)

        assert totals.blocked

    anyio.run(run)


def test_an_operator_interrupt_is_recorded_as_a_deliberate_stop() -> None:
    async def run() -> None:
        listener = FakeListener()
        socket = FakeSocket(error=KeyboardInterrupt())

        with pytest.raises(BaseExceptionGroup) as raised:
            await worker.run_session(listener, socket, _TRANSACTION_ID, worker.SessionTotals())

        assert worker.is_interrupt(raised.value)
        assert listener.detached == [(_SESSION_ID, "STOPPED")]
        assert listener.failures == []

    anyio.run(run)


def test_notifications_handled_before_a_signal_are_still_reported() -> None:
    """취소로 세션이 끝나도 처리한 건수를 잃지 않아야 운영자 보고가 사실과 맞는다."""

    async def run() -> None:
        listener = FakeListener()
        socket = SlowSocket(payloads=("first^body",))

        async def stop() -> None:
            await anyio.sleep(0.05)
            os.kill(os.getpid(), signal.SIGTERM)

        summaries: list[str] = []
        async with anyio.create_task_group() as task_group:
            _ = task_group.start_soon(stop)
            summaries.append(await worker.run_sessions(listener, socket, 0))

        assert listener.payloads == ["first^body"]
        assert summaries == ["sessions=1 notifications=1 blocked=False reason=STOPPED"]

    anyio.run(run)


def test_only_a_pure_interrupt_counts_as_a_clean_stop() -> None:
    assert worker.is_interrupt(KeyboardInterrupt())
    assert worker.is_interrupt(BaseExceptionGroup("stop", [KeyboardInterrupt()]))
    assert not worker.is_interrupt(RealtimeFrameError("body is empty"))
    assert not worker.is_interrupt(
        BaseExceptionGroup("mixed", [KeyboardInterrupt(), RuntimeError("boom")])
    )


@final
@dataclass
class SlowSocket:
    """본문을 낸 뒤 끊기지 않는 연결. 취소 시점의 집계를 확인한다."""

    payloads: tuple[str, ...] = ()

    async def stream(self) -> AsyncIterator[str]:
        for payload in self.payloads:
            yield payload
        await anyio.sleep_forever()


@final
@dataclass
class BlockingSocket:
    """끊기지 않는 연결. 취소 경로를 확인하기 위한 대역이다."""

    async def stream(self) -> AsyncIterator[str]:
        await anyio.sleep_forever()
        yield ""


def test_cancellation_is_recorded_as_a_deliberate_stop() -> None:
    async def run() -> None:
        listener = FakeListener()

        async def session() -> None:
            await worker.run_session(
                listener,
                BlockingSocket(),
                _TRANSACTION_ID,
                worker.SessionTotals(),
            )

        async with anyio.create_task_group() as task_group:
            _ = task_group.start_soon(session)
            await anyio.sleep(0.05)
            task_group.cancel_scope.cancel()

        assert listener.detached == [(_SESSION_ID, "STOPPED")]

    anyio.run(run)


def test_a_signal_closes_the_session_and_ends_the_loop() -> None:
    """컨테이너 정지에서도 세션이 닫혀야 다음 기동이 남은 연결 세션을 만나지 않는다."""

    async def run() -> None:
        listener = FakeListener()

        async def stop() -> None:
            await anyio.sleep(0.05)
            os.kill(os.getpid(), signal.SIGTERM)

        summaries: list[str] = []

        async with anyio.create_task_group() as task_group:
            _ = task_group.start_soon(stop)
            summaries.append(await worker.run_sessions(listener, BlockingSocket(), 0))

        assert listener.detached == [(_SESSION_ID, "STOPPED")]
        assert summaries == ["sessions=1 notifications=0 blocked=False reason=STOPPED"]

    anyio.run(run)


def test_backoff_grows_and_stops_at_the_contract_ceiling() -> None:
    assert [worker.backoff_seconds(attempt) for attempt in range(8)] == [
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
        30.0,
    ]


def test_a_healthy_session_resets_the_reconnect_wait() -> None:
    """백오프는 **연속 실패**에 증가한다. 누적 세션 수로 세면 오래 잘 돌수록 느려진다.

    2026-08-27 실측: KIS 모의 웹소켓이 매시 정각에 연결을 끊는데, 우리 쪽 대기가 2→4→8→30초로
    자라 하루가 지나면 항상 30초가 됐다. 한 시간 정상 수신한 세션은 실패 연속이 아니다.
    """
    streak = worker.ReconnectStreak()

    streak.record(healthy=True)
    assert streak.wait_seconds() == 1.0

    streak.record(healthy=False)
    assert streak.wait_seconds() == 2.0
    streak.record(healthy=False)
    assert streak.wait_seconds() == 4.0

    # 다시 정상 세션이 하나 지나가면 처음으로 돌아간다.
    streak.record(healthy=True)
    assert streak.wait_seconds() == 1.0


def test_repeated_immediate_failures_still_escalate_to_the_ceiling() -> None:
    """즉시 실패가 반복되면 상한까지 올라간다. 자격증명·네트워크 장애를 두드리지 않는다."""
    streak = worker.ReconnectStreak()

    waits: list[float] = []
    for _ in range(8):
        streak.record(healthy=False)
        waits.append(streak.wait_seconds())

    assert waits == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 30.0]


def test_a_session_that_received_a_notification_counts_as_healthy() -> None:
    """프레임을 받았다면 연결은 성립했다. 그 뒤의 단절은 실패 연속이 아니다."""
    assert worker.session_was_healthy(notifications=1, duration_seconds=0.0) is True


def test_a_long_lived_session_counts_as_healthy_even_with_no_frames() -> None:
    """통보 없는 조용한 장에서도 오래 붙어 있었으면 정상이다."""
    assert worker.session_was_healthy(notifications=0, duration_seconds=120.0) is True


def test_an_instant_failure_with_no_frames_is_not_healthy() -> None:
    assert worker.session_was_healthy(notifications=0, duration_seconds=0.5) is False
