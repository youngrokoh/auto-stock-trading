"""자동매매 복귀 규칙(거래 안전 정책 §6). 순수 함수다.

정책은 서버 재시작·거래일 변경·자격증명 환경 변경 시 상태가 **항상** `DISABLED`로 돌아간다고
정한다. '항상'이므로 규칙이 한 경로에만 있으면 안 된다 — 계획 경로만 리셋하고 제출 게이트와
조회가 저장된 값을 그대로 믿으면, 어제 켠 상태가 오늘 살아 있는 것처럼 보인다.

자격증명 환경 변경은 기록이 환경별로 분리돼 있어 구조적으로 처리된다(다른 환경의 기록은 읽히지
않고, 없는 기록은 `DISABLED`다). 여기서 다루는 것은 거래일 변경이다.
"""

from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.orders.models import AutomationState

if TYPE_CHECKING:
    from datetime import date

    from auto_stock_trading.domain.orders.records import AutomationRecord

# 계획 경로가 감사 기록에 쓰는 사유와 같은 값이어야 한다. 갈라지면 감사에서 원인이 둘로 보인다.
STALE_TRADING_DAY_REASON: Final = "TRADING_DAY_CHANGED"


def is_stale_trading_day(record: AutomationRecord, trading_date: date) -> bool:
    """기록이 지난 거래일의 것이고 아직 `DISABLED`가 아니면 되돌릴 대상이다.

    이미 `DISABLED`면 되돌릴 것이 없고 사유를 덮어쓰지도 않는다. 거래일을 모르는 기록은 지난
    거래일 것이라고 단정할 수 없으므로 건드리지 않는다.
    """
    return (
        record.trading_date is not None
        and record.trading_date != trading_date
        and record.state is not AutomationState.DISABLED
    )


def effective_automation_state(
    record: AutomationRecord | None,
    trading_date: date,
) -> AutomationState:
    """실제로 동작을 지배하는 상태. 저장된 값이 지난 거래일이면 `DISABLED`다.

    조회는 쓰기를 하지 않는다. 저장 사실은 그대로 두고 '지금 무엇이 성립하는가'만 계산한다 —
    그래야 화면이 꺼진 자동매매를 가동 중으로 보여주지 않는다.
    """
    if record is None:
        return AutomationState.DISABLED
    if is_stale_trading_day(record, trading_date):
        return AutomationState.DISABLED
    return record.state
