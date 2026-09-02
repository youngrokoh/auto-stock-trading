"""여러 분류 원천을 하나의 `SectorSource`로 합친다(ADR-0021).

주식은 KOSPI200 업종 코드, ETF는 추종 지수다. 두 taxonomy가 섞이지만 키가 겹치지 않으면 한도
계산에는 문제가 없다 — 업종 한도는 같은 키끼리의 합에만 걸린다.
"""

from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from auto_stock_trading.application.trading.planning import SectorSource


@final
class ChainedSectorSource:
    """앞에서부터 물어 첫 번째 분류를 돌려준다. 어디에도 없으면 None — 미분류다."""

    def __init__(self, *sources: SectorSource) -> None:
        self._sources = sources

    async def sector(self, symbol: str) -> str | None:
        for source in self._sources:
            sector = await source.sector(symbol)
            if sector is not None:
                return sector
        return None
