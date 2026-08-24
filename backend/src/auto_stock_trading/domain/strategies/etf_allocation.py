"""ETF 모멘텀 자산배분 유니버스. 사용자가 2026-08-24에 승인한 6종이다.

**이름으로 고르지 않았다.** `market.etf_nav`의 원천 필드로 걸렀다: 추적배수 1.00(정책 §1이
레버리지·인버스 신규 매수를 금지한다), 순자산총액 상위, 그리고 추종지수가 서로 다른 자산군.

구간은 가장 늦게 상장된 자산(미국채 20년+, 2023-03-14)이 정한다. 그 앞 구간에는 자산배분이 성립하지
않으므로 백테스트 시작점으로 쓴다. 자산군을 줄여 구간을 늘리는 대안은 검토했고, 자산배분 전략은
자산군이 서로 다를 때 의미가 생기므로 다양성을 택했다(사용자 승인).
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final


class AssetClass(StrEnum):
    """자산군. 하나에 하나의 ETF만 들어간다."""

    DOMESTIC_EQUITY = "domestic_equity"
    US_EQUITY = "us_equity"
    US_GROWTH = "us_growth"
    GOLD = "gold"
    US_TREASURY = "us_treasury"
    CASH_PROXY = "cash_proxy"


@dataclass(frozen=True, slots=True)
class AllocationEntry:
    """유니버스 한 종목. 수치는 2026-08-24 수집 스냅샷에서 읽은 사실이다."""

    symbol: str
    asset_class: AssetClass
    index_name: str
    listed_on: date
    tracking_multiple: int
    net_asset_total: int


ALLOCATION_UNIVERSE: Final = (
    AllocationEntry(
        symbol="069500",
        asset_class=AssetClass.DOMESTIC_EQUITY,
        index_name="KOSPI200",
        listed_on=date(2002, 10, 14),
        tracking_multiple=1,
        net_asset_total=260_643,
    ),
    AllocationEntry(
        symbol="360750",
        asset_class=AssetClass.US_EQUITY,
        index_name="S&P 500",
        listed_on=date(2020, 8, 7),
        tracking_multiple=1,
        net_asset_total=209_545,
    ),
    AllocationEntry(
        symbol="133690",
        asset_class=AssetClass.US_GROWTH,
        index_name="NASDAQ 100",
        listed_on=date(2010, 10, 18),
        tracking_multiple=1,
        net_asset_total=117_922,
    ),
    AllocationEntry(
        symbol="411060",
        asset_class=AssetClass.GOLD,
        index_name="KRX 금현물지수",
        listed_on=date(2021, 12, 15),
        tracking_multiple=1,
        net_asset_total=40_751,
    ),
    AllocationEntry(
        symbol="453850",
        asset_class=AssetClass.US_TREASURY,
        index_name="Bloomberg U.S Treasury 20+ Year Total Return Index",
        listed_on=date(2023, 3, 14),
        tracking_multiple=1,
        net_asset_total=15_031,
    ),
    AllocationEntry(
        symbol="357870",
        asset_class=AssetClass.CASH_PROXY,
        index_name="KIS CD금리투자 총수익지수",
        listed_on=date(2020, 7, 7),
        tracking_multiple=1,
        net_asset_total=35_489,
    ),
)

# 공통 구간의 시작. 가장 늦은 상장일이며, 그 앞에는 6자산 배분이 성립하지 않는다.
ALLOCATION_WINDOW_START: Final = max(entry.listed_on for entry in ALLOCATION_UNIVERSE)


def allocation_symbols() -> tuple[str, ...]:
    """수집·백테스트가 쓰는 종목코드. 정렬해 돌려주므로 실행 순서가 재현된다."""
    return tuple(sorted(entry.symbol for entry in ALLOCATION_UNIVERSE))
