from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from auto_stock_trading.domain.market_data.models import (
        InstrumentTarget,
        RawBrokerResponse,
    )


@dataclass(frozen=True, slots=True)
class InvestorFlow:
    symbol: str
    trading_date: date
    individual_net_quantity: int
    foreign_net_quantity: int
    institution_net_quantity: int
    individual_net_value: int
    foreign_net_value: int
    institution_net_value: int
    source: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class VersionedInvestorFlow:
    symbol: str
    trading_date: date
    individual_net_quantity: int
    foreign_net_quantity: int
    institution_net_quantity: int
    individual_net_value: int
    foreign_net_value: int
    institution_net_value: int
    source: str
    received_at: datetime
    version: int
    valid_from: datetime
    superseded_at: datetime | None


@dataclass(frozen=True, slots=True)
class InvestorFlowBundle:
    target: InstrumentTarget
    flows: tuple[InvestorFlow, ...]
    raw: RawBrokerResponse
    collected_at: datetime
    # 투자자 필드가 빈 문자열로 온 거래일. 값을 만들지 않았음을 호출자가 알 수 있어야 한다.
    skipped_blank_dates: tuple[date, ...] = ()
