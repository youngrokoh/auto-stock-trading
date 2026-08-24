"""투영과 전송 유스케이스(ADR-0014 결정 2·4·7·8).

전송 실패가 매매를 막지 않고, 실패가 사실로 남고, 폴 상한을 넘으면 요약으로 대체된다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, final
from uuid import UUID, uuid4

import anyio

from auto_stock_trading.application.notifications.dispatch import (
    NO_CREDENTIALS_REASON,
    DeliveryOutcome,
    NotificationDispatcher,
    OutboxEntry,
)
from auto_stock_trading.domain.notifications.events import (
    EventSource,
    NotificationCandidate,
    NotificationSeverity,
)
from auto_stock_trading.domain.orders.models import OrderSide, OrderState

_ENVIRONMENT: Final = "paper"
_NOW: Final = datetime(2026, 8, 24, 5, 3, 11, tzinfo=UTC)


def _candidate(
    *,
    source_id: UUID | None = None,
    state: OrderState = OrderState.FILLED,
    occurred_at: datetime | None = None,
) -> NotificationCandidate:
    return NotificationCandidate(
        source=EventSource.ORDER_EVENT,
        source_id=source_id or uuid4(),
        occurred_at=occurred_at or _NOW,
        previous_state=OrderState.SUBMITTED.value,
        state=state.value,
        reason_code="FILL_NOTIFICATION",
        symbol="005930",
        symbol_name="삼성전자",
        side=OrderSide.BUY,
        quantity=2,
        limit_price=Decimal(250_000),
        broker_order_id="0000117057",
        event_type=None,
        rule_code=None,
    )


def _listener_candidate() -> NotificationCandidate:
    return NotificationCandidate(
        source=EventSource.AUTOMATION_EVENT,
        source_id=uuid4(),
        occurred_at=_NOW,
        previous_state=None,
        state=None,
        reason_code="LISTENER_ATTACHED",
        symbol=None,
        symbol_name=None,
        side=None,
        quantity=None,
        limit_price=None,
        broker_order_id=None,
        event_type="listener_state",
        rule_code=None,
    )


@final
@dataclass
class FakeStore:
    candidates: tuple[NotificationCandidate, ...] = ()
    watermark: datetime | None = _NOW - timedelta(days=1)
    saved: list[OutboxEntry] = field(default_factory=list)
    pending: list[OutboxEntry] = field(default_factory=list)
    marked_sent: list[tuple[UUID, str | None]] = field(default_factory=list)
    failures: list[tuple[UUID, str]] = field(default_factory=list)
    watermarks_set: list[datetime] = field(default_factory=list)

    async def projection_watermark(self, environment: str) -> datetime | None:
        _ = environment
        return self.watermark

    async def set_projection_watermark(self, environment: str, at: datetime) -> None:
        _ = environment
        self.watermarks_set.append(at)
        self.watermark = at

    async def unprojected_events(
        self,
        environment: str,
        since: datetime,
    ) -> tuple[NotificationCandidate, ...]:
        _ = environment
        return tuple(c for c in self.candidates if c.occurred_at >= since)

    async def save_outbox(self, entries: tuple[OutboxEntry, ...]) -> int:
        self.saved.extend(entries)
        self.pending.extend(entry for entry in entries if entry.state == "pending")
        return len(entries)

    async def pending_entries(self, environment: str, limit: int) -> tuple[OutboxEntry, ...]:
        _ = environment
        return tuple(self.pending[:limit])

    async def mark_sent(self, entry_id: UUID, at: datetime, note: str | None) -> None:
        _ = at
        self.marked_sent.append((entry_id, note))
        self.pending = [entry for entry in self.pending if entry.entry_id != entry_id]

    async def mark_failed(self, entry_id: UUID, error: str, at: datetime) -> None:
        _ = at
        self.failures.append((entry_id, error))

    async def close(self) -> None:
        return None


@final
@dataclass
class FakeSender:
    failure: Exception | None = None
    outcome_error: str | None = None
    sent: list[str] = field(default_factory=list)
    configured: bool = True

    async def send(self, body: str) -> DeliveryOutcome:
        if self.failure is not None:
            raise self.failure
        self.sent.append(body)
        if self.outcome_error is not None:
            return DeliveryOutcome(delivered=False, error=self.outcome_error, retry_after=None)
        return DeliveryOutcome(delivered=True, error=None, retry_after=None)

    async def close(self) -> None:
        return None


def _dispatcher(
    store: FakeStore,
    sender: FakeSender | None,
    *,
    cap: int = 10,
) -> NotificationDispatcher:
    return NotificationDispatcher(
        store=store,
        sender=sender,
        environment=_ENVIRONMENT,
        poll_cap=cap,
    )


def test_only_notifiable_events_are_projected() -> None:
    async def scenario() -> None:
        store = FakeStore(candidates=(_candidate(), _listener_candidate()))
        sender = FakeSender()

        summary = await _dispatcher(store, sender).dispatch(_NOW)

        assert summary.projected == 1
        assert len(store.saved) == 1
        assert store.saved[0].source == EventSource.ORDER_EVENT.value

    anyio.run(scenario)


def test_a_forbidden_field_is_stored_as_failed_and_never_sent() -> None:
    """조용히 버리지 않는다 — 보내지 못했다는 사실이 남는다(계약 §저장)."""

    async def scenario() -> None:
        blocked = NotificationCandidate(
            source=EventSource.AUTOMATION_EVENT,
            source_id=uuid4(),
            occurred_at=_NOW,
            previous_state=None,
            state=None,
            reason_code="account=4aec6939a6d3",
            symbol=None,
            symbol_name=None,
            side=None,
            quantity=None,
            limit_price=None,
            broker_order_id=None,
            event_type="api_failure",
            rule_code=None,
        )
        store = FakeStore(candidates=(blocked,))
        sender = FakeSender()

        summary = await _dispatcher(store, sender).dispatch(_NOW)

        assert summary.projected == 1
        assert store.saved[0].state == "failed"
        assert store.saved[0].last_error == "FORBIDDEN_FIELD"
        assert store.saved[0].body == ""
        assert sender.sent == []

    anyio.run(scenario)


def test_pending_entries_are_sent_and_marked() -> None:
    async def scenario() -> None:
        store = FakeStore(candidates=(_candidate(),))
        sender = FakeSender()

        summary = await _dispatcher(store, sender).dispatch(_NOW)

        assert summary.sent == 1
        assert summary.failed == 0
        assert len(sender.sent) == 1
        assert "삼성전자" in sender.sent[0]
        assert len(store.marked_sent) == 1

    anyio.run(scenario)


def test_a_transport_failure_is_recorded_and_does_not_raise() -> None:
    """전송 실패는 매매를 막지 않는다. 예외를 밖으로 올리지 않고 사실로 남긴다."""

    async def scenario() -> None:
        store = FakeStore(candidates=(_candidate(),))
        sender = FakeSender(failure=TimeoutError("timeout"))

        summary = await _dispatcher(store, sender).dispatch(_NOW)

        assert summary.sent == 0
        assert summary.failed == 1
        assert store.failures[0][1].startswith("TimeoutError")
        assert store.marked_sent == []

    anyio.run(scenario)


def test_a_rejected_response_is_a_failure_even_with_http_200() -> None:
    async def scenario() -> None:
        store = FakeStore(candidates=(_candidate(),))
        sender = FakeSender(outcome_error="400 chat not found")

        summary = await _dispatcher(store, sender).dispatch(_NOW)

        assert summary.sent == 0
        assert summary.failed == 1
        assert store.failures[0][1] == "400 chat not found"

    anyio.run(scenario)


def test_exceeding_the_poll_cap_sends_one_summary_instead() -> None:
    """개별 200건을 보내면 한도에 걸리고 사람도 읽지 못한다(결정 7)."""

    async def scenario() -> None:
        many = tuple(_candidate() for _ in range(5))
        store = FakeStore(candidates=many)
        sender = FakeSender()

        summary = await _dispatcher(store, sender, cap=3).dispatch(_NOW)

        assert summary.summarized is True
        assert len(sender.sent) == 1
        body = sender.sent[0]
        assert "5" in body
        # 생략된 건수를 명시한다.
        assert "생략" in body
        # 대체된 행은 개별 전달되지 않았음을 사실로 남긴다.
        assert all(note == "SUMMARIZED" for _, note in store.marked_sent)
        assert len(store.marked_sent) == 5

    anyio.run(scenario)


def test_without_credentials_nothing_is_sent_and_the_watermark_is_not_moved() -> None:
    """자격증명 없는 실행이 워터마크만 옮기면 그 사이 이벤트가 조용히 지나간다."""

    async def scenario() -> None:
        store = FakeStore(candidates=(_candidate(),), watermark=None)

        summary = await _dispatcher(store, None).dispatch(_NOW)

        assert summary.reason == NO_CREDENTIALS_REASON
        assert summary.sent == 0
        assert store.saved == []
        assert store.watermarks_set == []

    anyio.run(scenario)


def test_the_first_run_projects_only_the_current_day_and_records_the_watermark() -> None:
    """워터마크 없이 anti-join만 돌리면 과거 전체가 한꺼번에 알림이 된다."""

    async def scenario() -> None:
        old = _candidate(occurred_at=_NOW - timedelta(days=3))
        today = _candidate()
        store = FakeStore(candidates=(old, today), watermark=None)
        sender = FakeSender()

        summary = await _dispatcher(store, sender).dispatch(_NOW)

        assert summary.projected == 1
        assert len(store.watermarks_set) == 1
        # 당일 00:00 KST 이후만 대상이다.
        assert store.watermarks_set[0] < _NOW

    anyio.run(scenario)


def test_severity_is_carried_into_the_outbox_row() -> None:
    async def scenario() -> None:
        blocked_risk = NotificationCandidate(
            source=EventSource.RISK_DECISION,
            source_id=uuid4(),
            occurred_at=_NOW,
            previous_state=None,
            state="blocked",
            reason_code=None,
            symbol="005930",
            symbol_name="삼성전자",
            side=OrderSide.BUY,
            quantity=2,
            limit_price=Decimal(250_000),
            broker_order_id=None,
            event_type=None,
            rule_code="RISK_SYMBOL_EXPOSURE",
        )
        store = FakeStore(candidates=(blocked_risk,))

        _ = await _dispatcher(store, FakeSender()).dispatch(_NOW)

        assert store.saved[0].severity == NotificationSeverity.WARNING.value

    anyio.run(scenario)
