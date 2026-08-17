from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, final
from uuid import UUID

from fastapi.testclient import TestClient

from auto_stock_trading.api.app import create_app
from auto_stock_trading.domain.market_data.adjustment_datasets import (
    AdjustedBarRecord,
    AdjustmentDatasetRecord,
    DatasetActionRecord,
)
from auto_stock_trading.domain.market_data.adjustments import AdjustmentMethod
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateAction,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionRange,
    CorporateActionType,
    TimePrecision,
    VersionedCorporateAction,
)
from auto_stock_trading.domain.market_data.models import (
    Instrument,
    ProductType,
    Quote,
    VersionedDailyBar,
)
from auto_stock_trading.settings.runtime import Environment, Settings

if TYPE_CHECKING:
    from auto_stock_trading.domain.market_data.investor_flows import VersionedInvestorFlow
    from auto_stock_trading.domain.market_data.listed_shares import (
        VersionedListedShareCount,
    )
    from auto_stock_trading.domain.market_data.minute_bars import VersionedMinuteBar

_SYMBOL = "069500"
_DATASET_ID = UUID(int=1)
_BAR_ID = UUID(int=2)
_ACTION_ID = UUID(int=3)
_ACTION_KEY = UUID(int=4)
_ANNOUNCED_AT = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
_CORRECTED_AT = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
_KNOWLEDGE_CUTOFF = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)


@final
class StubProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@final
class StubMarketDataReader:
    async def instruments(self) -> tuple[Instrument, ...]:
        result = await self.instrument(_SYMBOL)
        assert result is not None
        return (result,)

    async def instrument(self, symbol: str) -> Instrument | None:
        if symbol != _SYMBOL:
            return None
        return Instrument(
            country="KR",
            exchange="XKRX",
            symbol=symbol,
            product_type=ProductType.ETF,
            currency="KRW",
            name="KODEX 200",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="active",
            source="KIS",
            source_as_of=date(2026, 8, 14),
        )

    async def quote(self, symbol: str) -> Quote | None:
        _ = symbol
        return None

    async def daily_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[VersionedDailyBar, ...]:
        _ = (symbol, start_date, end_date)
        return ()

    async def listed_share_count(self, symbol: str) -> VersionedListedShareCount | None:
        _ = symbol
        return None

    async def investor_flows(
        self,
        symbol: str,
        limit: int,
    ) -> tuple[VersionedInvestorFlow, ...]:
        _ = (symbol, limit)
        return ()

    async def minute_bars(
        self,
        symbol: str,
        trading_date: date,
    ) -> tuple[VersionedMinuteBar, ...]:
        _ = (symbol, trading_date)
        return ()

    async def close(self) -> None:
        return None


def _distribution(cash_amount: Decimal, available_at: datetime) -> CorporateAction:
    return CorporateAction(
        action_type=CorporateActionType.ETF_DISTRIBUTION,
        lifecycle=CorporateActionLifecycle.CONFIRMED,
        quality=CorporateActionQuality.VERIFIED,
        announced_at=None,
        announcement_date=_ANNOUNCED_AT.date(),
        time_precision=TimePrecision.DATE,
        ex_date=date(2026, 7, 30),
        effective_date=None,
        record_date=date(2026, 7, 31),
        payment_date=None,
        share_multiplier=None,
        cash_amount=cash_amount,
        currency="KRW",
        subscription_price=None,
        related_instrument_id=None,
        source="KODEX",
        source_event_id="test-distribution-1",
        source_reference="https://example.test/distribution",
        available_at=available_at,
        received_at=available_at,
    )


_VERSION_1 = VersionedCorporateAction(
    action=_distribution(Decimal(180), _ANNOUNCED_AT),
    corporate_action_id=_ACTION_ID,
    action_key=_ACTION_KEY,
    version=1,
    valid_from=_ANNOUNCED_AT,
    superseded_at=_CORRECTED_AT,
)
_VERSION_2 = VersionedCorporateAction(
    action=_distribution(Decimal(183), _CORRECTED_AT),
    corporate_action_id=UUID(int=5),
    action_key=_ACTION_KEY,
    version=2,
    valid_from=_CORRECTED_AT,
    superseded_at=None,
)


@final
class StubCorporateActionReader:
    async def read_current(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        return (_VERSION_2,) if query.symbol == _SYMBOL else ()

    async def read_history(
        self,
        query: CorporateActionRange,
    ) -> tuple[VersionedCorporateAction, ...]:
        return (_VERSION_1, _VERSION_2) if query.symbol == _SYMBOL else ()

    async def read_as_of(
        self,
        query: CorporateActionRange,
        knowledge_cutoff_at: datetime,
    ) -> tuple[VersionedCorporateAction, ...]:
        if query.symbol != _SYMBOL:
            return ()
        return (_VERSION_1,) if knowledge_cutoff_at < _CORRECTED_AT else (_VERSION_2,)

    async def close(self) -> None:
        return None


def _dataset() -> AdjustmentDatasetRecord:
    return AdjustmentDatasetRecord(
        dataset_id=_DATASET_ID,
        symbol=_SYMBOL,
        method=AdjustmentMethod.TOTAL_RETURN,
        interval="1d",
        range_start=date(2026, 7, 1),
        price_cutoff_date=date(2026, 8, 13),
        knowledge_cutoff_at=_KNOWLEDGE_CUTOFF,
        algorithm_version="krx-t2-adjust-v1",
        input_bar_version_hash="a" * 64,
        action_version_hash="b" * 64,
        status="published",
        generated_at=_KNOWLEDGE_CUTOFF,
        superseded_at=None,
        failure_code=None,
    )


def _adjusted_bar() -> AdjustedBarRecord:
    return AdjustedBarRecord(
        dataset_id=_DATASET_ID,
        source_bar_id=_BAR_ID,
        trading_date=date(2026, 7, 29),
        open_price=Decimal("89240.12345678"),
        high_price=Decimal("89600.00000000"),
        low_price=Decimal("89100.00000000"),
        close_price=Decimal("89422.00000000"),
        volume=1_000_000,
        trading_value=Decimal(89_422_000_000),
        price_factor=Decimal("0.9979577032531667"),
        volume_factor=Decimal("1.0000000000000000"),
        source="KIS",
        source_bar_version=1,
    )


def _dataset_action() -> DatasetActionRecord:
    return DatasetActionRecord(
        dataset_id=_DATASET_ID,
        corporate_action_id=_ACTION_ID,
        action_key=_ACTION_KEY,
        action_version=2,
        event_date=date(2026, 7, 30),
        event_price_factor=Decimal("0.9979577032531667"),
        event_volume_factor=Decimal("1.0000000000000000"),
        source="KODEX",
    )


@final
class StubAdjustedPriceReader:
    async def read_dataset(self, dataset_id: UUID) -> AdjustmentDatasetRecord | None:
        return _dataset() if dataset_id == _DATASET_ID else None

    async def read_latest_published(
        self,
        symbol: str,
        method: AdjustmentMethod,
    ) -> AdjustmentDatasetRecord | None:
        if symbol != _SYMBOL or method is not AdjustmentMethod.TOTAL_RETURN:
            return None
        return _dataset()

    async def read_datasets_for_action(
        self,
        action_key: UUID,
    ) -> tuple[AdjustmentDatasetRecord, ...]:
        return (_dataset(),) if action_key == _ACTION_KEY else ()

    async def read_adjusted_bars(self, dataset_id: UUID) -> tuple[AdjustedBarRecord, ...]:
        return (_adjusted_bar(),) if dataset_id == _DATASET_ID else ()

    async def read_dataset_actions(self, dataset_id: UUID) -> tuple[DatasetActionRecord, ...]:
        return (_dataset_action(),) if dataset_id == _DATASET_ID else ()

    async def close(self) -> None:
        return None


def _client() -> TestClient:
    app = create_app(
        settings=Settings(environment=Environment.TEST),
        database_probe_factory=StubProbe,
        cache_probe_factory=StubProbe,
        market_data_reader_factory=StubMarketDataReader,
        corporate_action_reader_factory=StubCorporateActionReader,
        adjusted_price_reader_factory=StubAdjustedPriceReader,
    )
    return TestClient(app)


_EXPECTED_DATASET: dict[str, object] = {
    "dataset_id": str(_DATASET_ID),
    "symbol": _SYMBOL,
    "method": "total_return",
    "interval": "1d",
    "range_start": "2026-07-01",
    "price_cutoff_date": "2026-08-13",
    "knowledge_cutoff_at": "2026-08-14T07:00:00Z",
    "algorithm_version": "krx-t2-adjust-v1",
    "input_bar_version_hash": "a" * 64,
    "action_version_hash": "b" * 64,
    "status": "published",
    "generated_at": "2026-08-14T07:00:00Z",
    "superseded_at": None,
    "failure_code": None,
}
_EXPECTED_BAR: dict[str, object] = {
    "trading_date": "2026-07-29",
    "open_price": "89240.12345678",
    "high_price": "89600.00000000",
    "low_price": "89100.00000000",
    "close_price": "89422.00000000",
    "volume": 1_000_000,
    "trading_value": "89422000000",
    "price_factor": "0.9979577032531667",
    "volume_factor": "1.0000000000000000",
    "source": "KIS",
    "source_bar_id": str(_BAR_ID),
    "source_bar_version": 1,
}
_EXPECTED_APPLIED_ACTION: dict[str, object] = {
    "corporate_action_id": str(_ACTION_ID),
    "action_key": str(_ACTION_KEY),
    "action_version": 2,
    "event_date": "2026-07-30",
    "event_price_factor": "0.9979577032531667",
    "event_volume_factor": "1.0000000000000000",
    "source": "KODEX",
}
_EXPECTED_BUNDLE: dict[str, object] = {
    "dataset": _EXPECTED_DATASET,
    "bars": [_EXPECTED_BAR],
    "applied_actions": [_EXPECTED_APPLIED_ACTION],
}


def _expected_action_version(result: VersionedCorporateAction) -> dict[str, object]:
    return {
        "corporate_action_id": str(result.corporate_action_id),
        "action_key": str(_ACTION_KEY),
        "version": result.version,
        "valid_from": result.valid_from.isoformat().replace("+00:00", "Z"),
        "superseded_at": (
            result.superseded_at.isoformat().replace("+00:00", "Z")
            if result.superseded_at is not None
            else None
        ),
        "action_type": "etf_distribution",
        "lifecycle": "confirmed",
        "quality": "verified",
        "announced_at": None,
        "announcement_date": "2026-07-01",
        "time_precision": "date",
        "ex_date": "2026-07-30",
        "effective_date": None,
        "record_date": "2026-07-31",
        "payment_date": None,
        "share_multiplier": None,
        "cash_amount": str(result.action.cash_amount),
        "currency": "KRW",
        "subscription_price": None,
        "related_instrument_id": None,
        "source": "KODEX",
        "source_event_id": "test-distribution-1",
        "source_reference": "https://example.test/distribution",
        "available_at": result.action.available_at.isoformat().replace("+00:00", "Z"),
        "received_at": result.action.received_at.isoformat().replace("+00:00", "Z"),
    }


def _expected_actions_body(
    knowledge_cutoff_at: str | None,
    versions: tuple[VersionedCorporateAction, ...],
    *,
    include_history: bool = False,
) -> dict[str, object]:
    return {
        "symbol": _SYMBOL,
        "start_date": None,
        "end_date": None,
        "knowledge_cutoff_at": knowledge_cutoff_at,
        "include_history": include_history,
        "actions": [_expected_action_version(version) for version in versions],
    }


def test_adjusted_daily_bars_expose_dataset_lineage_and_sources() -> None:
    with _client() as client:
        response = client.get(
            f"/api/market-data/instruments/{_SYMBOL}/adjusted-daily-bars",
            params={"method": "total_return"},
        )

    assert response.status_code == 200
    assert response.json() == _EXPECTED_BUNDLE


def test_adjusted_dataset_lookup_by_id_and_action_impact() -> None:
    with _client() as client:
        by_id = client.get(f"/api/market-data/adjusted-datasets/{_DATASET_ID}")
        impact = client.get(f"/api/market-data/corporate-actions/{_ACTION_KEY}/adjusted-datasets")

    assert by_id.status_code == 200
    assert by_id.json() == _EXPECTED_BUNDLE
    assert impact.status_code == 200
    assert impact.json() == {
        "action_key": str(_ACTION_KEY),
        "datasets": [_EXPECTED_DATASET],
    }


def test_corporate_actions_list_supports_point_in_time_and_history() -> None:
    path = f"/api/market-data/instruments/{_SYMBOL}/corporate-actions"
    with _client() as client:
        current = client.get(path)
        as_of = client.get(path, params={"knowledge_cutoff_at": "2026-07-10T00:00:00Z"})
        history = client.get(path, params={"include_history": "true"})

    assert current.status_code == 200
    assert current.json() == _expected_actions_body(None, (_VERSION_2,))
    assert as_of.status_code == 200
    assert as_of.json() == _expected_actions_body("2026-07-10T00:00:00Z", (_VERSION_1,))
    assert history.status_code == 200
    assert history.json() == _expected_actions_body(
        None,
        (_VERSION_1, _VERSION_2),
        include_history=True,
    )


def test_adjusted_read_endpoints_reject_invalid_queries_and_missing_data() -> None:
    actions_path = f"/api/market-data/instruments/{_SYMBOL}/corporate-actions"
    with _client() as client:
        missing_dataset = client.get(
            "/api/market-data/instruments/999999/adjusted-daily-bars",
            params={"method": "total_return"},
        )
        unknown_dataset_id = client.get(f"/api/market-data/adjusted-datasets/{UUID(int=9)}")
        unknown_instrument = client.get("/api/market-data/instruments/999999/corporate-actions")
        invalid_method = client.get(
            f"/api/market-data/instruments/{_SYMBOL}/adjusted-daily-bars",
            params={"method": "adjusted"},
        )
        naive_cutoff = client.get(
            actions_path,
            params={"knowledge_cutoff_at": "2026-07-10T00:00:00"},
        )
        conflicting_query = client.get(
            actions_path,
            params={
                "knowledge_cutoff_at": "2026-07-10T00:00:00Z",
                "include_history": "true",
            },
        )
        invalid_range = client.get(
            actions_path,
            params={"start_date": "2026-08-14", "end_date": "2026-08-13"},
        )

    assert missing_dataset.status_code == 404
    assert unknown_dataset_id.status_code == 404
    assert unknown_instrument.status_code == 404
    assert invalid_method.status_code == 422
    assert naive_cutoff.status_code == 422
    assert conflicting_query.status_code == 422
    assert invalid_range.status_code == 422
