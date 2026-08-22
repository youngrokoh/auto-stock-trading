from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Final, override

from auto_stock_trading.domain.market_data.models import ProductType


class KrxMarket(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class UncoveredCostDateError(Exception):
    execution_date: date

    @override
    def __str__(self) -> str:
        return f"no cost rule set is effective for {self.execution_date.isoformat()}"


@dataclass(frozen=True, slots=True)
class CostRuleSet:
    version: str
    effective_from: date
    fee_rate: Decimal
    stock_slippage_rate: Decimal
    etf_slippage_rate: Decimal
    kospi_stock_sell_tax_rate: Decimal
    kosdaq_stock_sell_tax_rate: Decimal
    source: str


@dataclass(frozen=True, slots=True)
class TradeCosts:
    fee: Decimal
    slippage: Decimal
    tax: Decimal

    @property
    def total(self) -> Decimal:
        return self.fee + self.slippage + self.tax


_RESEARCH_FEE_RATE: Final = Decimal("0.0002")
_RESEARCH_STOCK_SLIPPAGE_RATE: Final = Decimal("0.0010")
_RESEARCH_ETF_SLIPPAGE_RATE: Final = Decimal("0.0005")

# 거래 안전 정책 §5의 연구 기본 가정(수수료·슬리피지)과 법정 매도세 기준선.
# 코스피는 증권거래세 + 농어촌특별세 0.15%, 코스닥은 증권거래세만 부과한다.
#
# 2020~2024 세트는 **연구 가정**이다(2026-08-22 사용자 승인). 증권거래세 단계 인하 일정으로 알려진
# 값을 넣었고, 공식 고시로 재확인하기 전까지 백테스트 전용이다. 주문 경로는 이 값을 쓰지 않는다.
#   2020년: 거래세 0.10% -> 코스피 0.25% / 코스닥 0.25%
#   2021~2022년: 0.08% -> 0.23% / 0.23%
#   2023년: 0.05% -> 0.20% / 0.20%
#   2024년: 0.03% -> 0.18% / 0.18%
# 2025~2026 세트는 정책 §5의 현행 표에서 왔다.
#   2025년: 거래세 0% -> 코스피 0.15% / 코스닥 0.15%
#   2026년: 거래세 0.05% -> 코스피 0.20% / 코스닥 0.20%
COST_RULE_SETS: Final = (
    CostRuleSet(
        version="research-krx-2020",
        effective_from=date(2020, 1, 1),
        fee_rate=_RESEARCH_FEE_RATE,
        stock_slippage_rate=_RESEARCH_STOCK_SLIPPAGE_RATE,
        etf_slippage_rate=_RESEARCH_ETF_SLIPPAGE_RATE,
        kospi_stock_sell_tax_rate=Decimal("0.0025"),
        kosdaq_stock_sell_tax_rate=Decimal("0.0025"),
        source="연구 가정: 증권거래세 단계 인하 일정(공식 고시 재확인 전, 백테스트 전용)",
    ),
    CostRuleSet(
        version="research-krx-2021",
        effective_from=date(2021, 1, 1),
        fee_rate=_RESEARCH_FEE_RATE,
        stock_slippage_rate=_RESEARCH_STOCK_SLIPPAGE_RATE,
        etf_slippage_rate=_RESEARCH_ETF_SLIPPAGE_RATE,
        kospi_stock_sell_tax_rate=Decimal("0.0023"),
        kosdaq_stock_sell_tax_rate=Decimal("0.0023"),
        source="연구 가정: 증권거래세 단계 인하 일정(공식 고시 재확인 전, 백테스트 전용)",
    ),
    CostRuleSet(
        version="research-krx-2023",
        effective_from=date(2023, 1, 1),
        fee_rate=_RESEARCH_FEE_RATE,
        stock_slippage_rate=_RESEARCH_STOCK_SLIPPAGE_RATE,
        etf_slippage_rate=_RESEARCH_ETF_SLIPPAGE_RATE,
        kospi_stock_sell_tax_rate=Decimal("0.0020"),
        kosdaq_stock_sell_tax_rate=Decimal("0.0020"),
        source="연구 가정: 증권거래세 단계 인하 일정(공식 고시 재확인 전, 백테스트 전용)",
    ),
    CostRuleSet(
        version="research-krx-2024",
        effective_from=date(2024, 1, 1),
        fee_rate=_RESEARCH_FEE_RATE,
        stock_slippage_rate=_RESEARCH_STOCK_SLIPPAGE_RATE,
        etf_slippage_rate=_RESEARCH_ETF_SLIPPAGE_RATE,
        kospi_stock_sell_tax_rate=Decimal("0.0018"),
        kosdaq_stock_sell_tax_rate=Decimal("0.0018"),
        source="연구 가정: 증권거래세 단계 인하 일정(공식 고시 재확인 전, 백테스트 전용)",
    ),
    CostRuleSet(
        version="research-krx-2025",
        effective_from=date(2025, 1, 1),
        fee_rate=_RESEARCH_FEE_RATE,
        stock_slippage_rate=_RESEARCH_STOCK_SLIPPAGE_RATE,
        etf_slippage_rate=_RESEARCH_ETF_SLIPPAGE_RATE,
        kospi_stock_sell_tax_rate=Decimal("0.0015"),
        kosdaq_stock_sell_tax_rate=Decimal("0.0015"),
        source="증권거래세법 시행령(2025 세율)·농어촌특별세법 제5조",
    ),
    CostRuleSet(
        version="research-krx-2026",
        effective_from=date(2026, 1, 1),
        fee_rate=_RESEARCH_FEE_RATE,
        stock_slippage_rate=_RESEARCH_STOCK_SLIPPAGE_RATE,
        etf_slippage_rate=_RESEARCH_ETF_SLIPPAGE_RATE,
        kospi_stock_sell_tax_rate=Decimal("0.0020"),
        kosdaq_stock_sell_tax_rate=Decimal("0.0020"),
        source="거래 안전 정책 §5 (증권거래세법 시행령 2026-01-01·농어촌특별세법 제5조)",
    ),
)


def cost_rule_set_for(execution_date: date) -> CostRuleSet:
    effective = [rule for rule in COST_RULE_SETS if rule.effective_from <= execution_date]
    if not effective:
        raise UncoveredCostDateError(execution_date)
    return max(effective, key=lambda rule: rule.effective_from)


def cost_rule_versions_for_window(start_date: date, end_date: date) -> tuple[str, ...]:
    first_rule = cost_rule_set_for(start_date)
    return tuple(
        rule.version
        for rule in sorted(COST_RULE_SETS, key=lambda rule: rule.effective_from)
        if rule.effective_from >= first_rule.effective_from and rule.effective_from <= end_date
    )


def _truncate_to_won(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal(1), rounding=ROUND_DOWN)


def _sell_tax_rate(
    rule_set: CostRuleSet,
    product_type: ProductType,
    market: KrxMarket,
) -> Decimal:
    if product_type is ProductType.ETF:
        return Decimal(0)
    if market is KrxMarket.KOSPI:
        return rule_set.kospi_stock_sell_tax_rate
    return rule_set.kosdaq_stock_sell_tax_rate


def trade_costs(
    rule_set: CostRuleSet,
    product_type: ProductType,
    market: KrxMarket,
    side: TradeSide,
    gross_amount: Decimal,
) -> TradeCosts:
    slippage_rate = (
        rule_set.etf_slippage_rate
        if product_type is ProductType.ETF
        else rule_set.stock_slippage_rate
    )
    tax_rate = (
        _sell_tax_rate(rule_set, product_type, market) if side is TradeSide.SELL else Decimal(0)
    )
    return TradeCosts(
        fee=_truncate_to_won(gross_amount * rule_set.fee_rate),
        slippage=_truncate_to_won(gross_amount * slippage_rate),
        tax=_truncate_to_won(gross_amount * tax_rate),
    )
