"""API 테스트용 기동 리셋 스텁.

`create_app`은 기본값으로 실제 PostgreSQL 저장소를 만든다(정책 §6의 기동 리셋). 단위 API 테스트는
인프라 없이 돌아야 하므로 이 스텁을 주입한다 — 기존 프로브·리더 팩토리와 같은 이음새다.
"""

from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from auto_stock_trading.application.trading.planning import AutomationTransition
    from auto_stock_trading.domain.orders.records import AutomationRecord


@final
class NoAutomationReset:
    """기록이 없는 환경. 리셋 함수는 전이 없이 DISABLED를 돌려준다."""

    async def automation_record(self, environment: str) -> AutomationRecord | None:
        _ = environment
        return None

    async def transition_automation(self, transition: AutomationTransition) -> AutomationRecord:
        raise AssertionError(transition)  # 기록이 없으면 전이하지 않는다

    async def close(self) -> None:
        return None
