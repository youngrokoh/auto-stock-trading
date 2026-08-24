"""상시 프로세스 기동 시 자동매매를 되돌리는 공용 경로(거래 안전 정책 §6).

정책의 '항상'은 경로를 가리지 않는다는 뜻이다. 거래일 변경은 `domain/orders/recovery.py`의 순수
규칙이 계획·제출 게이트·조회에서 함께 쓰이지만, **서버 재시작**은 저장된 사실을 실제로 바꿔야
한다 — 프로세스가 죽었다는 것은 저장된 값에서 계산할 수 없다.

그래서 기동 자체가 상태 머신의 입력이다. 상시 프로세스가 시작하면 사유 `PROCESS_START`로
`DISABLED`로 전이하고, 사람이 다시 켜야 주문이 나간다. 세션 내부 재연결은 프로세스 시작이 아니므로
여기를 호출하지 않는다. 적용 대상은 API 서버와 체결통보 리스너다(2026-08-24 사용자 승인) — 시장
데이터 worker·스케줄러는 거래 상태를 건드리지 않는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol
from zoneinfo import ZoneInfo

from auto_stock_trading.application.trading.planning import AutomationTransition
from auto_stock_trading.domain.orders.models import AutomationState

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.orders.records import AutomationRecord

_SEOUL: Final = ZoneInfo("Asia/Seoul")

# 감사에서 원인이 한 값으로 보이도록 리스너와 API가 같은 사유를 쓴다.
PROCESS_START_REASON: Final = "PROCESS_START"


class AutomationResetStore(Protocol):
    """기동 리셋에 필요한 최소 저장소 표면."""

    async def automation_record(self, environment: str) -> AutomationRecord | None: ...

    async def transition_automation(
        self,
        transition: AutomationTransition,
    ) -> AutomationRecord: ...


async def reset_automation_on_start(
    store: AutomationResetStore,
    environment: str,
    now: datetime,
) -> AutomationState:
    """자동매매를 `DISABLED`로 되돌린다. 이미 꺼져 있으면 기록을 남기지 않는다.

    이미 `DISABLED`인 기록을 다시 쓰면 사람이 껐다는 사유가 기동 사유로 덮인다. 되돌릴 것이 없을
    때는 아무것도 쓰지 않는 것이 감사 기록을 보존한다.
    """
    record = await store.automation_record(environment)
    if record is None or record.state is AutomationState.DISABLED:
        return AutomationState.DISABLED
    applied = await store.transition_automation(
        AutomationTransition(
            environment=environment,
            requested=AutomationState.DISABLED,
            reason_code=PROCESS_START_REASON,
            occurred_at=now,
            trading_date=now.astimezone(_SEOUL).date(),
        )
    )
    return applied.state
