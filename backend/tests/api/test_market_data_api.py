from datetime import UTC, date, datetime
from decimal import Decimal
from typing import final

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.domain.market_data.investor_flows import VersionedInvestorFlow
from auto_stock_trading.domain.market_data.listed_shares import VersionedListedShareCount
from auto_stock_trading.domain.market_data.minute_bars import MinuteBar, VersionedMinuteBar
from auto_stock_trading.domain.market_data.models import (
    BarFinality,
    DailyBar,
    Instrument,
    ProductType,
    Quote,
    VersionedDailyBar,
)
from auto_stock_trading.settings.runtime import Environment, Settings
from tests.api.automation_stub import NoAutomationReset


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@final
class StubMarketDataReader:
    async def instruments(self) -> tuple[Instrument, ...]:
        result = await self.instrument("005930")
        assert result is not None
        return (result,)

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
    ) -> tuple[VersionedDailyBar, ...]:
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
        return (
            VersionedDailyBar(
                bar=bar,
                finality=BarFinality.PENDING,
                confirmed_at=None,
                version=1,
                valid_from=bar.received_at,
                superseded_at=None,
            ),
        )

    async def listed_share_count(self, symbol: str) -> VersionedListedShareCount | None:
        _ = symbol
        return None

    async def investor_flows(
        self,
        symbol: str,
        limit: int,
    ) -> tuple[VersionedInvestorFlow, ...]:
        if symbol != "005930":
            return ()
        received_at = datetime(2026, 8, 17, 1, 0, tzinfo=UTC)
        return (
            VersionedInvestorFlow(
                symbol=symbol,
                trading_date=date(2026, 8, 14),
                individual_net_quantity=-3049225,
                foreign_net_quantity=4913433,
                institution_net_quantity=-1830920,
                individual_net_value=-829332,
                foreign_net_value=1336152,
                institution_net_value=-497830,
                source="KIS",
                received_at=received_at,
                version=1,
                valid_from=received_at,
                superseded_at=None,
            ),
        )[:limit]

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]:
        if symbol != "005930" or trading_date != date(2026, 8, 13):
            return ()
        received_at = datetime(2026, 8, 13, 6, 45, tzinfo=UTC)
        return (
            VersionedMinuteBar(
                bar=MinuteBar(
                    symbol=symbol,
                    trading_date=trading_date,
                    bar_started_at=datetime(2026, 8, 13, 0, 0, tzinfo=UTC),
                    open_price=Decimal(72800),
                    high_price=Decimal(72900),
                    low_price=Decimal(72700),
                    close_price=Decimal(72850),
                    volume=15_000,
                    cumulative_trading_value=Decimal(1_092_000_000),
                    source="KIS",
                    received_at=received_at,
                ),
                finality=BarFinality.PENDING,
                confirmed_at=None,
                version=1,
                valid_from=received_at,
                superseded_at=None,
            ),
        )

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        automation_reset_factory=NoAutomationReset,
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        market_data_reader_factory=StubMarketDataReader,
    )
    return TestClient(app)


def test_instrument_list_exposes_collected_instruments() -> None:
    with _client() as client:
        response = client.get("/api/market-data/instruments")

    assert response.status_code == 200
    assert response.json() == {
        "instruments": [
            {
                "country": "KR",
                "exchange": "XKRX",
                "symbol": "005930",
                "product_type": "stock",
                "currency": "KRW",
                "name": "삼성전자",
                "english_name": "Samsung Electronics",
                "listed_on": "1975-06-11",
                "delisted_on": None,
                "trading_status": "active",
                "source": "KIS",
                "source_as_of": "2026-08-14",
                # 이 fake reader는 클래스 사실을 주지 않는다. 모른다는 뜻의 null이다.
                "share_class": None,
            }
        ]
    }


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
    assert bars.json()["bars"][0]["version"] == 1
    assert bars.json()["bars"][0]["finality"] == "pending"
    assert bars.json()["bars"][0]["confirmed_at"] is None
    assert bars.json()["bars"][0]["valid_from"] == "2026-08-14T01:00:00Z"


def test_minute_bars_expose_versioned_facts_for_a_trading_date() -> None:
    with _client() as client:
        response = client.get(
            "/api/market-data/instruments/005930/minute-bars",
            params={"trading_date": "2026-08-13"},
        )
        empty = client.get(
            "/api/market-data/instruments/005930/minute-bars",
            params={"trading_date": "2026-08-12"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "005930",
        "interval": "1m",
        "trading_date": "2026-08-13",
        "source": "KIS",
        "bars": [
            {
                "bar_started_at": "2026-08-13T00:00:00Z",
                "open_price": "72800",
                "high_price": "72900",
                "low_price": "72700",
                "close_price": "72850",
                "volume": 15_000,
                "cumulative_trading_value": "1092000000",
                "source": "KIS",
                "received_at": "2026-08-13T06:45:00Z",
                "finality": "pending",
                "confirmed_at": None,
                "version": 1,
                "valid_from": "2026-08-13T06:45:00Z",
            }
        ],
    }
    assert empty.status_code == 200
    assert empty.json()["bars"] == []


def test_market_data_endpoints_return_explicit_not_found_and_invalid_range() -> None:
    with _client() as client:
        missing = client.get("/api/market-data/instruments/999999")
        invalid = client.get(
            "/api/market-data/instruments/005930/daily-bars",
            params={"start_date": "2026-08-14", "end_date": "2026-08-13"},
        )
        missing_minutes = client.get(
            "/api/market-data/instruments/999999/minute-bars",
            params={"trading_date": "2026-08-13"},
        )
        missing_date = client.get("/api/market-data/instruments/005930/minute-bars")

    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert missing_minutes.status_code == 404
    assert missing_date.status_code == 422


def test_investor_flows_expose_units_and_versioned_rows() -> None:
    with _client() as client:
        response = client.get("/api/market-data/instruments/005930/investor-flows")
        unknown = client.get("/api/market-data/instruments/999999/investor-flows")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "005930",
        "source": "KIS",
        "quantity_unit": "share",
        "value_unit": "million_krw",
        "flows": [
            {
                "trading_date": "2026-08-14",
                "individual_net_quantity": -3049225,
                "foreign_net_quantity": 4913433,
                "institution_net_quantity": -1830920,
                "individual_net_value": -829332,
                "foreign_net_value": 1336152,
                "institution_net_value": -497830,
                "received_at": "2026-08-17T01:00:00Z",
                "version": 1,
            }
        ],
    }
    assert unknown.status_code == 404
