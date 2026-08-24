"""외부 알림 투영과 전송 유스케이스(ADR-0014).

폴러가 아직 아웃박스에 없는 이벤트를 투영하고, 미발신 행을 순서대로 보낸다. 전송 실패는 예외를
밖으로 올리지 않는다 — 알림은 이미 저장된 사실의 사본이므로 매매를 막지 않는다(결정 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING, Final, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from auto_stock_trading.domain.notifications.events import (
    build_message,
    is_notifiable,
)

if TYPE_CHECKING:
    from auto_stock_trading.domain.notifications.events import NotificationCandidate

_SEOUL: Final = ZoneInfo("Asia/Seoul")

NO_CREDENTIALS_REASON: Final = "NO_CREDENTIALS"
SUMMARIZED_NOTE: Final = "SUMMARIZED"

_PENDING: Final = "pending"
_FAILED: Final = "failed"
# 요약이 실제 적체 규모를 세도록 상한보다 넉넉히 읽는다. 이 수를 넘는 적체는 다음 폴이 이어
# 요약한다.
_SUMMARY_SCAN: Final = 1000


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """아웃박스 한 행. 저장된 값 그대로이며 전송 시점에 다시 조립하지 않는다."""

    entry_id: UUID
    environment: str
    source: str
    source_id: UUID
    kind: str
    severity: str
    body: str
    state: str
    last_error: str | None
    event_occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    delivered: bool
    error: str | None
    retry_after: int | None


@dataclass(frozen=True, slots=True)
class DispatchSummary:
    projected: int
    sent: int
    failed: int
    summarized: bool
    reason: str | None


class NotificationStore(Protocol):
    async def projection_watermark(self, environment: str) -> datetime | None: ...

    async def set_projection_watermark(self, environment: str, at: datetime) -> None: ...

    async def unprojected_events(
        self,
        environment: str,
        since: datetime,
    ) -> tuple[NotificationCandidate, ...]: ...

    async def save_outbox(self, entries: tuple[OutboxEntry, ...]) -> int: ...

    async def pending_entries(self, environment: str, limit: int) -> tuple[OutboxEntry, ...]: ...

    async def mark_sent(self, entry_id: UUID, at: datetime, note: str | None) -> None: ...

    async def mark_failed(self, entry_id: UUID, error: str, at: datetime) -> None: ...


class NotificationSender(Protocol):
    async def send(self, body: str) -> DeliveryOutcome: ...


def _day_start(now: datetime) -> datetime:
    """첫 실행의 투영 시작점. 당일 00:00 KST다."""
    seoul = now.astimezone(_SEOUL)
    return datetime.combine(seoul.date(), time(0, 0), _SEOUL)


def _summary_body(entries: tuple[OutboxEntry, ...], cap: int) -> str:
    """적체 전체를 한 건으로 알린다. 개별 전송을 생략한 건수를 숨기지 않는다."""
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    breakdown = " · ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))
    warnings = sum(1 for entry in entries if entry.severity == "warning")
    return "\n".join(
        (
            f"[요약] 알림 {len(entries)}건 (상한 {cap})",
            breakdown,
            f"경고 {warnings}건",
            f"개별 전송 생략 {len(entries)}건 — 상세는 콘솔에서 확인",
        )
    )


@dataclass(frozen=True, slots=True)
class NotificationDispatcher:
    store: NotificationStore
    sender: NotificationSender | None
    environment: str
    poll_cap: int

    async def dispatch(self, now: datetime) -> DispatchSummary:
        """투영 후 전송한다. 자격증명이 없으면 아무것도 하지 않는다."""
        if self.sender is None:
            # 투영만 하고 워터마크를 옮기면 그 사이 이벤트가 조용히 지나간다. 둘 다 하지 않는다.
            return DispatchSummary(
                projected=0,
                sent=0,
                failed=0,
                summarized=False,
                reason=NO_CREDENTIALS_REASON,
            )
        projected = await self._project(now)
        pending = await self.store.pending_entries(self.environment, _SUMMARY_SCAN)
        if len(pending) > self.poll_cap:
            return await self._send_summary(pending, projected, now)
        sent, failed = await self._send_each(pending, now)
        return DispatchSummary(
            projected=projected,
            sent=sent,
            failed=failed,
            summarized=False,
            reason=None,
        )

    async def _project(self, now: datetime) -> int:
        watermark = await self.store.projection_watermark(self.environment)
        since = watermark if watermark is not None else _day_start(now)
        candidates = await self.store.unprojected_events(self.environment, since)
        entries = tuple(
            self._entry(candidate, now) for candidate in candidates if is_notifiable(candidate)
        )
        saved = await self.store.save_outbox(entries) if entries else 0
        if watermark is None:
            await self.store.set_projection_watermark(self.environment, since)
        return saved

    def _entry(self, candidate: NotificationCandidate, now: datetime) -> OutboxEntry:
        message = build_message(candidate)
        rejected = message.rejected_reason is not None
        _ = now
        return OutboxEntry(
            entry_id=uuid4(),
            environment=self.environment,
            source=candidate.source.value,
            source_id=candidate.source_id,
            kind=message.kind.value,
            severity=message.severity.value,
            body=message.body,
            # 금지 필드에 걸린 행은 보내지 않되 사실로 남긴다(결정 8).
            state=_FAILED if rejected else _PENDING,
            last_error=message.rejected_reason,
            event_occurred_at=candidate.occurred_at,
        )

    async def _send_summary(
        self,
        pending: tuple[OutboxEntry, ...],
        projected: int,
        now: datetime,
    ) -> DispatchSummary:
        body = _summary_body(pending, self.poll_cap)
        outcome = await self._deliver(body)
        if outcome.error is not None:
            for entry in pending:
                await self.store.mark_failed(entry.entry_id, outcome.error, now)
            return DispatchSummary(
                projected=projected,
                sent=0,
                failed=len(pending),
                summarized=True,
                reason=None,
            )
        for entry in pending:
            # 같은 알림이 다음 폴에서 개별 전송되면 요약의 의미가 없다. 대체됐음을 사실로 남긴다.
            await self.store.mark_sent(entry.entry_id, now, SUMMARIZED_NOTE)
        return DispatchSummary(
            projected=projected,
            sent=1,
            failed=0,
            summarized=True,
            reason=None,
        )

    async def _send_each(
        self,
        pending: tuple[OutboxEntry, ...],
        now: datetime,
    ) -> tuple[int, int]:
        sent = 0
        failed = 0
        for entry in pending:
            outcome = await self._deliver(entry.body)
            if outcome.error is not None:
                await self.store.mark_failed(entry.entry_id, outcome.error, now)
                failed += 1
                continue
            await self.store.mark_sent(entry.entry_id, now, None)
            sent += 1
        return sent, failed

    async def _deliver(self, body: str) -> DeliveryOutcome:
        if self.sender is None:
            return DeliveryOutcome(delivered=False, error=NO_CREDENTIALS_REASON, retry_after=None)
        try:
            return await self.sender.send(body)
        except Exception as error:  # noqa: BLE001 — 어떤 전송 오류도 매매로 전파되지 않게 사실로 바꾼다
            # 전송 실패가 매매 경로로 전파되지 않게 여기서 사실로 바꾼다(결정 4).
            return DeliveryOutcome(
                delivered=False,
                error=f"{type(error).__name__}: {error}"[:500],
                retry_after=None,
            )
