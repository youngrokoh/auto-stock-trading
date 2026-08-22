"""학습 표본 타입(ML 신호 계약 §특징·§목표).

특징과 목표는 금액이 아니라 비율·순위이므로 `float`로 담는다. 금액 규칙(`Decimal`)은 시세·주문
경로에 적용되며, 여기서는 수치 계산 라이브러리와의 경계를 단순하게 유지하는 편이 안전하다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True, slots=True)
class TrainingSample:
    symbol: str
    signal_date: date
    features: tuple[float, ...]
    # 학습 목표: 같은 날 후보들 사이의 백분위 순위(0~1).
    target: float
    # 평가용 원 초과수익. 계약의 상위 K 초과수익·적중률은 순위가 아니라 이 값으로 계산한다.
    excess: float = 0.0
