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
        _ = cost_rule_set_for(date(2024, 12, 31))


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
