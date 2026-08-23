"""재무 특징(ML 신호 계약 §특징). 순수 함수다.

지표 정의는 재무 지표 정의 계약이 갖는다. 여기서는 시점 정합 선택과 가격 대비 정규화만 한다.
규칙형 v3가 쓰는 두 요인과 **같은 정의**를 써서 "같은 정보로 ML이 더 잘 조합하는가"를 판정할 수
있게 한다.
"""

from typing import TYPE_CHECKING, Final

from auto_stock_trading.domain.strategies.composite_rank import point_in_time_fact

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date
    from decimal import Decimal

    from auto_stock_trading.domain.strategies.composite_rank import AnnualFact

FUNDAMENTAL_FEATURE_NAMES: Final = ("earnings_yield", "roe")


def fundamental_features(
    facts: Sequence[AnnualFact],
    signal_date: date,
    close_price: Decimal,
) -> Mapping[str, Decimal] | None:
    """시그널일에 알 수 있었던 보고서로 재무 특징을 만든다.

    보고서가 없거나 필요한 값이 하나라도 없으면 `None`이다. 가격 특징과 같은 규칙으로, 0이나
    평균으로 채우지 않고 그 종목-일 표본을 만들지 않는다.
    """
    if close_price <= 0:
        return None
    fact = point_in_time_fact(facts, signal_date)
    if fact is None or fact.eps is None or fact.roe is None:
        return None
    return {
        "earnings_yield": fact.eps / close_price,
        "roe": fact.roe,
    }
