"""DART 고유번호 매핑 사실. 배당 수집이 종목코드로 회사를 찾으려면 이 매핑이 필요하다."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from auto_stock_trading.domain.market_data.models import RawBrokerResponse


@dataclass(frozen=True, slots=True)
class DartCorpCode:
    symbol: str
    corp_code: str
    corp_name: str
    source: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class DartCorpCodeBundle:
    codes: tuple[DartCorpCode, ...]
    raw: RawBrokerResponse
    collected_at: datetime
