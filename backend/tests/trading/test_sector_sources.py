from typing import final

import anyio

from auto_stock_trading.application.trading.sector_sources import ChainedSectorSource


@final
class _Source:
    def __init__(self, sectors: dict[str, str]) -> None:
        self._sectors = sectors
        self.asked: list[str] = []

    async def sector(self, symbol: str) -> str | None:
        self.asked.append(symbol)
        return self._sectors.get(symbol)


def test_the_first_source_that_classifies_wins() -> None:
    async def run() -> None:
        stocks = _Source({"005930": "5"})
        etfs = _Source({"069500": "KOSPI200", "005930": "SHOULD_NOT_BE_ASKED"})
        source = ChainedSectorSource(stocks, etfs)

        assert await source.sector("005930") == "5"
        assert await source.sector("069500") == "KOSPI200"
        # 주식에서 분류됐으면 ETF 원천에는 묻지 않는다.
        assert etfs.asked == ["069500"]

    anyio.run(run)


def test_unclassified_everywhere_stays_unclassified() -> None:
    async def run() -> None:
        source = ChainedSectorSource(_Source({}), _Source({}))

        assert await source.sector("133690") is None

    anyio.run(run)
