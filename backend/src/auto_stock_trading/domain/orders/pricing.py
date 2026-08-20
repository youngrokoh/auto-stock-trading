from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.orders.models import OrderSide

# KRX 호가단위(2023-01-25 개정). ETF·ETN은 가격 구간과 무관하게 5원이다.
_STOCK_TICK_BANDS: Final[tuple[tuple[Decimal, Decimal], ...]] = (
    (Decimal(2000), Decimal(1)),
    (Decimal(5000), Decimal(5)),
    (Decimal(20000), Decimal(10)),
    (Decimal(50000), Decimal(50)),
    (Decimal(200000), Decimal(100)),
    (Decimal(500000), Decimal(500)),
)
_STOCK_TOP_TICK: Final = Decimal(1000)
_ETF_TICK: Final = Decimal(5)
_PRICE_BAND: Final = Decimal("0.01")


def tick_size(price: Decimal, product_type: ProductType) -> Decimal:
    if product_type is ProductType.ETF:
        return _ETF_TICK
    for upper_bound, tick in _STOCK_TICK_BANDS:
        if price < upper_bound:
            return tick
    return _STOCK_TOP_TICK


def round_to_tick(price: Decimal, product_type: ProductType) -> Decimal:
    tick = tick_size(price, product_type)
    steps = (price / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return steps * tick


def offset_limit_price(
    reference_price: Decimal,
    product_type: ProductType,
    offset: Decimal,
) -> Decimal:
    """기준가에서 상대 버전트만큼 옮긴 지정가. 절대가를 사람이 지정하지 않는다.

    검증용으로 즉시 체결되지 않는 주문을 만들 때 쓴다. 정책 §4의 ±1% 밴드를 넘는 버전트는
    기존 `RISK_ORDER_PRICE_BAND` 규칙이 거절하므로 여기서 따로 막지 않는다.
    """
    return round_to_tick(reference_price * (Decimal(1) + offset), product_type)


def within_price_band(side: OrderSide, limit_price: Decimal, reference_price: Decimal) -> bool:
    if side is OrderSide.BUY:
        return limit_price <= reference_price * (1 + _PRICE_BAND)
    return limit_price >= reference_price * (1 - _PRICE_BAND)
