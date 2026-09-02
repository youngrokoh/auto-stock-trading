"""ETF 업종 분류 사실과 위험검사용 업종 키 규칙(ADR-0021).

ETF의 업종 키는 추종 지수다. 주식의 KOSPI200 업종 코드와 taxonomy가 다르지만 키가 겹치지 않으면
한도 계산에는 문제가 없다 — 업종 한도는 같은 키끼리의 합에만 걸린다. 분류는 한도를 **넓히는**
방향으로 작용하므로 넓혀도 되는 것만 넓힌다: 추적배수가 1인 것, 관측이 신선한 것.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

# 추종 지수는 거의 바뀌지 않으므로 느슨해도 되지만, 기준이 없으면 "언제 수집한 것인지 모르는 값"이
# 위험 입력이 된다. 주 1회 수집이면 여유 있게 충족하고, 수집이 몇 주 멈추면 미분류로 넘어간다.
CLASSIFICATION_MAX_AGE: Final = timedelta(days=30)
UNIT_TRACKING_MULTIPLE: Final = Decimal(1)


@dataclass(frozen=True, slots=True)
class EtfIndexClassification:
    symbol: str
    index_name: str
    tracking_multiple: Decimal
    source: str
    as_of: datetime
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedEtfIndexClassification:
    symbol: str
    index_name: str
    tracking_multiple: Decimal
    source: str
    as_of: datetime
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None


def classification_sector(fact: EtfIndexClassification, *, now: datetime) -> str | None:
    """위험검사가 쓰는 업종 키. None이면 미분류 한도로 남는다(fail-closed).

    지수 문자열은 원천이 준 그대로 쓴다. 정규화는 "S&P 500"과 "S&P500"을 같게 만들 수도, 다른
    지수를 잘못 합칠 수도 있다 — 원문이 다르면 다른 키다.
    """
    if fact.tracking_multiple != UNIT_TRACKING_MULTIPLE:
        return None
    if now - fact.as_of > CLASSIFICATION_MAX_AGE:
        return None
    if not fact.index_name.strip():
        return None
    return fact.index_name
