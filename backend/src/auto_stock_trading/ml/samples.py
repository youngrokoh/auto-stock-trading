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
    target: float
