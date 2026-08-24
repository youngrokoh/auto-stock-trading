"""상시 프로세스 기동 시 자동매매 복귀(거래 안전 정책 §6).

정책은 서버 재시작에서도 상태가 **항상** `DISABLED`로 돌아간다고 정한다. 2026-08-24 실측에서
`api`·`worker` 컨테이너를 재시작했는데 `running`이 그대로 남았다 — 리셋이 체결통보 리스너 한
프로세스에만 있었고 그 리스너는 기본 구성에 없기 때문이다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Final, final
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.application.trading.startup import (
    PROCESS_START_REASON,
    reset_automation_on_start,
)
from auto_stock_trading.domain.orders.models import AutomationState
from auto_stock_trading.domain.orders.records import AutomationRecord

if TYPE_CHECKING:
    from auto_stock_trading.application.trading.planning import AutomationTransition

_SEOUL: Final = ZoneInfo("Asia/Seoul")
_ENVIRONMENT: Final = "paper"
_NOW: Final = datetime.combine(datetime(2026, 8, 24, tzinfo=UTC).date(), time(10, 11), _SEOUL)


@final
@dataclass
class FakeStore:
    state: AutomationState | None
    transitions: list[AutomationTransition] = field(default_factory=list)

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        if self.state is None:
            return None
        return AutomationRecord(
            environment=environment,
            state=self.state,
            reason_code="USER_COMMAND",
            trading_date=_NOW.astimezone(_SEOUL).date(),
            changed_at=_NOW,
        )

    async def transition_automation(self, transition: AutomationTransition) -> AutomationRecord:
        self.transitions.append(transition)
        self.state = transition.requested
        return AutomationRecord(
            environment=transition.environment,
            state=transition.requested,
            reason_code=transition.reason_code,
            trading_date=transition.trading_date,
            changed_at=transition.occurred_at,
        )


@pytest.mark.parametrize(
    "state",
    [
        AutomationState.ARMED,
        AutomationState.RUNNING,
        AutomationState.PAUSED,
        AutomationState.EMERGENCY_STOP,
    ],
)
def test_every_live_state_returns_to_disabled_on_process_start(state: AutomationState) -> None:
    async def scenario() -> None:
        store = FakeStore(state=state)

        applied = await reset_automation_on_start(store, _ENVIRONMENT, _NOW)

        assert applied is AutomationState.DISABLED
        (transition,) = store.transitions
        assert transition.requested is AutomationState.DISABLED
        assert transition.reason_code == PROCESS_START_REASON
        assert transition.trading_date == _NOW.astimezone(_SEOUL).date()

    anyio.run(scenario)


def test_an_already_disabled_state_is_not_rewritten() -> None:
    """사유를 덮어쓰지 않는다. 되돌릴 것이 없으면 기록도 남기지 않는다."""

    async def scenario() -> None:
        store = FakeStore(state=AutomationState.DISABLED)

        applied = await reset_automation_on_start(store, _ENVIRONMENT, _NOW)

        assert applied is AutomationState.DISABLED
        assert store.transitions == []

    anyio.run(scenario)


def test_a_missing_record_is_disabled_without_a_write() -> None:
    async def scenario() -> None:
        store = FakeStore(state=None)

        applied = await reset_automation_on_start(store, _ENVIRONMENT, _NOW)

        assert applied is AutomationState.DISABLED
        assert store.transitions == []

    anyio.run(scenario)


def test_the_trading_date_is_the_seoul_date_of_the_start() -> None:
    """UTC 날짜를 쓰면 09:00 KST 이전에 전날로 기록돼 다음 계획이 또 리셋한다."""

    async def scenario() -> None:
        store = FakeStore(state=AutomationState.RUNNING)
        day = datetime(2026, 8, 24, tzinfo=UTC).date()
        before_open = datetime.combine(day, time(8, 30), _SEOUL)

        _ = await reset_automation_on_start(store, _ENVIRONMENT, before_open)

        (transition,) = store.transitions
        assert transition.trading_date == before_open.astimezone(_SEOUL).date()

    anyio.run(scenario)
