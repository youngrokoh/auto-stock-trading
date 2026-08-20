from decimal import Decimal
from typing import Final

import pytest

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.orders.models import OrderSide
from auto_stock_trading.domain.orders.pricing import offset_limit_price, within_price_band

_REFERENCE: Final = Decimal(258500)


def test_a_zero_offset_keeps_the_tick_rounded_reference_price() -> None:
    assert offset_limit_price(_REFERENCE, ProductType.STOCK, Decimal(0)) == _REFERENCE


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        # 258,500 × 1.008 = 260,568 → 500원 호가단위 반올림
        (Decimal("0.008"), Decimal(260500)),
        (Decimal("-0.008"), Decimal(256500)),
        (Decimal("0.002"), Decimal(259000)),
    ],
)
def test_the_offset_moves_the_price_and_rounds_to_the_tick(
    offset: Decimal,
    expected: Decimal,
) -> None:
    assert offset_limit_price(_REFERENCE, ProductType.STOCK, offset) == expected


def test_an_etf_uses_the_five_won_tick() -> None:
    price = offset_limit_price(Decimal(12345), ProductType.ETF, Decimal("0.005"))

    assert price % Decimal(5) == 0
    assert price == Decimal(12405)


def test_the_band_only_blocks_the_direction_that_loses_money() -> None:
    """정책 §4의 밴드는 비대칭이다: 매수는 비싸게 사는 것을, 매도는 싸게 파는 것을 막는다.

    체결을 늦추는 방향(매도를 높게, 매수를 낮게)은 손실 위험이 아니므로 막지 않는다.
    """
    higher = offset_limit_price(_REFERENCE, ProductType.STOCK, Decimal("0.02"))
    lower = offset_limit_price(_REFERENCE, ProductType.STOCK, Decimal("-0.02"))

    assert within_price_band(OrderSide.SELL, higher, _REFERENCE)
    assert not within_price_band(OrderSide.SELL, lower, _REFERENCE)
    assert within_price_band(OrderSide.BUY, lower, _REFERENCE)
    assert not within_price_band(OrderSide.BUY, higher, _REFERENCE)


def test_a_small_offset_passes_the_band_in_both_directions() -> None:
    higher = offset_limit_price(_REFERENCE, ProductType.STOCK, Decimal("0.008"))
    lower = offset_limit_price(_REFERENCE, ProductType.STOCK, Decimal("-0.008"))

    assert within_price_band(OrderSide.SELL, higher, _REFERENCE)
    assert within_price_band(OrderSide.BUY, lower, _REFERENCE)
