from datetime import UTC, date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionRange,
    CorporateActionType,
    TimePrecision,
    VersionedCorporateAction,
)
from auto_stock_trading.domain.market_data.etf import (
    EtfListing,
    EtfNavSnapshot,
    VersionedEtfProfile,
)
from auto_stock_trading.settings.runtime import Environment, Settings

_NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _profile(symbol: str, name: str) -> VersionedEtfProfile:
    return VersionedEtfProfile(
        symbol=symbol,
        isin=f"KR7{symbol}007"[:12],
        name=name,
        source="KIS_MASTER",
        received_at=_NOW,
        version=1,
        valid_from=_NOW,
        superseded_at=None,
    )


def _snapshot() -> EtfNavSnapshot:
    return EtfNavSnapshot(
        symbol="069500",
        price=Decimal(110060),
        change_percent=Decimal("0.00"),
        volume=495,
        previous_volume=17088038,
        nav=Decimal("110371.90"),
        divergence_rate=Decimal("-0.28"),
        tracking_error=Decimal("0.39"),
        tracking_multiple=Decimal("1.00"),
        net_asset_total=260643,
        listed_shares=236150000,
        manager="삼성자산운용(ETF)",
        index_name="KOSPI200",
        listing_date=date(2002, 10, 14),
        currency="KRW",
        source="KIS",
        as_of=_NOW,
        received_at=_NOW,
    )


@final
class StubEtfReader:
    async def read_etf_list(self) -> tuple[EtfListing, ...]:
        return (
            EtfListing(profile=_profile("0000H0", "KODEX 인도Nifty미드캡100"), snapshot=None),
            EtfListing(profile=_profile("069500", "KODEX 200"), snapshot=_snapshot()),
        )

    async def read_etf(self, symbol: str) -> EtfListing | None:
        if symbol == "069500":
            return EtfListing(profile=_profile("069500", "KODEX 200"), snapshot=_snapshot())
        if symbol == "0000H0":
            return EtfListing(profile=_profile("0000H0", "KODEX 인도Nifty미드캡100"), snapshot=None)
        return None

    async def close(self) -> None:
        return None


@final
class StubCorporateActionReader:
    async def read_current(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        if query.symbol != "069500":
            return ()
        action = CorporateAction(
            action_type=CorporateActionType.ETF_DISTRIBUTION,
            lifecycle=CorporateActionLifecycle.CONFIRMED,
            quality=CorporateActionQuality.VERIFIED,
            announced_at=None,
            announcement_date=date(2026, 7, 1),
            time_precision=TimePrecision.DATE,
            ex_date=date(2026, 7, 30),
            effective_date=None,
            record_date=None,
            payment_date=None,
            share_multiplier=None,
            cash_amount=Decimal(183),
            currency="KRW",
            subscription_price=None,
            related_instrument_id=None,
            source="KODEX",
            source_event_id="kodex:2026-07-30",
            source_reference="fixture",
            available_at=_NOW,
            received_at=_NOW,
        )
        return (
            VersionedCorporateAction(
                action=action,
                corporate_action_id=UUID(int=31),
                action_key=UUID(int=32),
                version=1,
                valid_from=_NOW,
                superseded_at=None,
            ),
        )

    async def read_history(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        _ = query
        return ()

    async def read_as_of(
        self,
        query: CorporateActionRange,
        knowledge_cutoff_at: datetime,
    ) -> tuple[VersionedCorporateAction, ...]:
        _ = (query, knowledge_cutoff_at)
        return ()

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        etf_reader_factory=StubEtfReader,
        corporate_action_reader_factory=StubCorporateActionReader,
    )
    return TestClient(app)


_SNAPSHOT_JSON: dict[str, object] = {
    "price": "110060",
    "change_percent": "0.00",
    "volume": 495,
    "previous_volume": 17088038,
    "nav": "110371.90",
    "divergence_rate": "-0.28",
    "tracking_error": "0.39",
    "tracking_multiple": "1.00",
    "net_asset_total": 260643,
    "listed_shares": 236150000,
    "manager": "삼성자산운용(ETF)",
    "index_name": "KOSPI200",
    "listing_date": "2002-10-14",
    "currency": "KRW",
    "as_of": "2026-08-18T01:00:00Z",
    "received_at": "2026-08-18T01:00:00Z",
}


def test_etf_list_exposes_master_and_latest_snapshots_with_units() -> None:
    with _client() as client:
        response = client.get("/api/market-data/etfs")

    assert response.status_code == 200
    assert response.json() == {
        "source": "KIS",
        "master_source": "KIS_MASTER",
        "net_asset_unit": "hundred_million_krw",
        "etfs": [
            {
                "symbol": "0000H0",
                "isin": "KR70000H0007",
                "name": "KODEX 인도Nifty미드캡100",
                "snapshot": None,
            },
            {
                "symbol": "069500",
                "isin": "KR7069500007",
                "name": "KODEX 200",
                "snapshot": _SNAPSHOT_JSON,
            },
        ],
    }


def test_etf_detail_includes_distribution_yield_with_formula() -> None:
    with _client() as client:
        response = client.get("/api/market-data/etfs/069500")
        without_history = client.get("/api/market-data/etfs/0000H0")
        unknown = client.get("/api/market-data/etfs/999999")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "069500",
        "isin": "KR7069500007",
        "name": "KODEX 200",
        "source": "KIS",
        "master_source": "KIS_MASTER",
        "net_asset_unit": "hundred_million_krw",
        "snapshot": _SNAPSHOT_JSON,
        "distribution_yield": {
            "value": "0.17",
            "unavailable_reason": None,
            "formula": "최근 12개월 주당 분배금 합계 ÷ 현재가 × 100",
            "distribution_total": "183",
            "distribution_count": 1,
            "window_start": "2025-08-18",
            "window_end": "2026-08-18",
        },
    }
    assert without_history.status_code == 200
    assert without_history.json() == {
        "symbol": "0000H0",
        "isin": "KR70000H0007",
        "name": "KODEX 인도Nifty미드캡100",
        "source": "KIS",
        "master_source": "KIS_MASTER",
        "net_asset_unit": "hundred_million_krw",
        "snapshot": None,
        "distribution_yield": {
            "value": None,
            "unavailable_reason": "MISSING_SNAPSHOT",
            "formula": "최근 12개월 주당 분배금 합계 ÷ 현재가 × 100",
            "distribution_total": None,
            "distribution_count": 0,
            "window_start": None,
            "window_end": None,
        },
    }
    assert unknown.status_code == 404
