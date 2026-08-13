from datetime import UTC, date, datetime
from decimal import Decimal
from typing import final

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.domain.market_data.models import (
    DailyBar,
    Instrument,
    ProductType,
    Quote,
)
from auto_stock_trading.settings.runtime import Environment, Settings


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@final
class StubMarketDataReader:
    async def instrument(self, symbol: str) -> Instrument | None:
        if symbol != "005930":
            return None
        return Instrument(
            country="KR",
            exchange="XKRX",
            symbol=symbol,
            product_type=ProductType.STOCK,
            currency="KRW",
            name="삼성전자",
            english_name="Samsung Electronics",
            listed_on=date(1975, 6, 11),
            delisted_on=None,
            trading_status="active",
            source="KIS",
            source_as_of=date(2026, 8, 14),
        )

    async def quote(self, symbol: str) -> Quote | None:
        if symbol != "005930":
            return None
        received_at = datetime(2026, 8, 14, 1, tzinfo=UTC)
        return Quote(
            symbol=symbol,
            price=Decimal(73500),
            open_price=Decimal(72800),
            high_price=Decimal(74000),
            low_price=Decimal(72500),
            previous_close=Decimal(73000),
            change=Decimal(500),
            change_percent=Decimal("0.68"),
            volume=12_450_000,
            trading_value=Decimal(914_000_000_000),
            currency="KRW",
            source="KIS",
            as_of=received_at,
            received_at=received_at,
        )

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[DailyBar, ...]:
        if symbol != "005930":
            return ()
        bar = DailyBar(
            symbol=symbol,
            trading_date=date(2026, 8, 13),
            open_price=Decimal(72800),
            high_price=Decimal(74000),
            low_price=Decimal(72500),
            close_price=Decimal(73500),
            volume=12_450_000,
            trading_value=Decimal(914_000_000_000),
            adjusted=False,
            correction_code=None,
            split_ratio=None,
            source="KIS",
            received_at=datetime(2026, 8, 14, 1, tzinfo=UTC),
        )
        if start_date is not None and bar.trading_date < start_date:
            return ()
        if end_date is not None and bar.trading_date > end_date:
            return ()
        return (bar,)

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        market_data_reader_factory=StubMarketDataReader,
    )
    return TestClient(app)


def test_market_data_read_endpoints_include_source_and_as_of() -> None:
    with _client() as client:
        instrument = client.get("/api/market-data/instruments/005930")
        quote = client.get("/api/market-data/instruments/005930/quote")
        bars = client.get(
            "/api/market-data/instruments/005930/daily-bars",
            params={"start_date": "2026-08-13", "end_date": "2026-08-13"},
        )

    assert instrument.status_code == 200
    assert instrument.json()["product_type"] == "stock"
    assert instrument.json()["source_as_of"] == "2026-08-14"
    assert quote.status_code == 200
    assert quote.json()["source"] == "KIS"
    assert quote.json()["as_of"] == "2026-08-14T01:00:00Z"
    assert bars.status_code == 200
    assert bars.json()["interval"] == "1d"
    assert bars.json()["bars"][0]["adjusted"] is False


def test_market_data_endpoints_return_explicit_not_found_and_invalid_range() -> None:
    with _client() as client:
        missing = client.get("/api/market-data/instruments/999999")
        invalid = client.get(
            "/api/market-data/instruments/005930/daily-bars",
            params={"start_date": "2026-08-14", "end_date": "2026-08-13"},
        )

    assert missing.status_code == 404
    assert invalid.status_code == 422
