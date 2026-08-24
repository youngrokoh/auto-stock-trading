"""알림 발신 현황 조회 레코드. 저장된 아웃박스 행에서 그대로 읽는다."""

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 — 조회 응답 조립에서 실행 시점에 쓴다


@dataclass(frozen=True, slots=True)
class NotificationEntryRecord:
    """아웃박스 한 행의 조회용 표현. 본문은 담지 않는다 — 콘솔은 현황만 본다."""

    kind: str
    severity: str
    state: str
    attempts: int
    reason: str | None
    event_occurred_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationStatusRecord:
    pending: int
    failed: int
    sent: int
    oldest_pending_at: datetime | None
    recent: tuple[NotificationEntryRecord, ...]
