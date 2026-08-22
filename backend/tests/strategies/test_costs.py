from datetime import date
from decimal import Decimal

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.strategies.costs import (
    KrxMarket,
    TradeSide,
    UncoveredCostDateError,
    cost_rule_set_for,
    cost_rule_versions_for_window,
    trade_costs,
)


def test_window_rule_versions_cover_every_effective_rule() -> None:
    assert cost_rule_versions_for_window(date(2025, 6, 1), date(2026, 2, 1)) == (
        "research-krx-2025",
        "research-krx-2026",
    )
    assert cost_rule_versions_for_window(date(2026, 2, 1), date(2026, 8, 14)) == (
        "research-krx-2026",
    )


def test_rule_set_selects_latest_effective_version() -> None:
    rule_2025 = cost_rule_set_for(date(2025, 6, 2))
    rule_2026 = cost_rule_set_for(date(2026, 8, 14))
    assert rule_2025.version == "research-krx-2025"
    assert rule_2025.effective_from == date(2025, 1, 1)
    assert rule_2026.version == "research-krx-2026"
    assert rule_2026.effective_from == date(2026, 1, 1)


def test_rule_set_fails_closed_before_first_effective_date() -> None:
    with pytest.raises(UncoveredCostDateError):
        _ = cost_rule_set_for(date(2019, 12, 31))


def test_statutory_sell_tax_follows_the_staged_reduction() -> None:
    """연구 가정으로 기록한 단계 인하 일정(정책 §5). 연도 경계를 값으로 고정한다."""
    expected = {
        date(2020, 3, 2): ("research-krx-2020", Decimal("0.0025")),
        date(2021, 1, 4): ("research-krx-2021", Decimal("0.0023")),
        date(2022, 6, 1): ("research-krx-2021", Decimal("0.0023")),
        date(2023, 1, 2): ("research-krx-2023", Decimal("0.0020")),
        date(2024, 1, 2): ("research-krx-2024", Decimal("0.0018")),
        date(2025, 1, 2): ("research-krx-2025", Decimal("0.0015")),
        date(2026, 1, 2): ("research-krx-2026", Decimal("0.0020")),
    }
    for execution_date, (version, rate) in expected.items():
        rule = cost_rule_set_for(execution_date)
        assert rule.version == version
        assert rule.kospi_stock_sell_tax_rate == rate
        assert rule.kosdaq_stock_sell_tax_rate == rate


def test_a_2023_window_covers_every_rule_in_between() -> None:
    assert cost_rule_versions_for_window(date(2023, 7, 10), date(2026, 8, 14)) == (
        "research-krx-2023",
        "research-krx-2024",
        "research-krx-2025",
        "research-krx-2026",
    )


def test_etf_stays_tax_exempt_in_the_earlier_rule_sets() -> None:
    costs = trade_costs(
        cost_rule_set_for(date(2021, 5, 3)),
        ProductType.ETF,
        KrxMarket.KOSPI,
        TradeSide.SELL,
        Decimal(1_000_000),
    )
    assert costs.tax == Decimal(0)


def test_stock_buy_costs_apply_fee_and_slippage_only() -> None:
    costs = trade_costs(
        cost_rule_set_for(date(2026, 8, 14)),
        ProductType.STOCK,
        KrxMarket.KOSPI,
        TradeSide.BUY,
        Decimal(10_000_000),
    )
    assert costs.fee == Decimal(2000)
    assert costs.slippage == Decimal(10000)
    assert costs.tax == Decimal(0)
    assert costs.total == Decimal(12000)


def test_kospi_stock_sell_costs_include_2026_taxes() -> None:
    costs = trade_costs(
        cost_rule_set_for(date(2026, 8, 14)),
        ProductType.STOCK,
        KrxMarket.KOSPI,
        TradeSide.SELL,
        Decimal(10_000_000),
    )
    assert costs.fee == Decimal(2000)
    assert costs.slippage == Decimal(10000)
    assert costs.tax == Decimal(20000)


def test_kospi_stock_sell_tax_uses_2025_statutory_rate() -> None:
    costs = trade_costs(
        cost_rule_set_for(date(2025, 6, 2)),
        ProductType.STOCK,
        KrxMarket.KOSPI,
        TradeSide.SELL,
        Decimal(10_000_000),
    )
    assert costs.tax == Decimal(15000)


def test_etf_sell_is_tax_exempt_with_lower_slippage() -> None:
    costs = trade_costs(
        cost_rule_set_for(date(2026, 8, 14)),
        ProductType.ETF,
        KrxMarket.KOSPI,
        TradeSide.SELL,
        Decimal(10_000_000),
    )
    assert costs.fee == Decimal(2000)
    assert costs.slippage == Decimal(5000)
    assert costs.tax == Decimal(0)


def test_cost_items_truncate_below_one_won() -> None:
    costs = trade_costs(
        cost_rule_set_for(date(2026, 8, 14)),
        ProductType.STOCK,
        KrxMarket.KOSPI,
        TradeSide.SELL,
        Decimal(12345),
    )
    assert costs.fee == Decimal(2)
    assert costs.slippage == Decimal(12)
    assert costs.tax == Decimal(24)
