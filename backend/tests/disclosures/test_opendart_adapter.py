import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import anyio
import pytest

from auto_stock_trading.adapters.disclosures.dart_cash_dividend import DartContractError
from auto_stock_trading.adapters.disclosures.opendart_corporate_actions import (
    DartDividendTarget,
)
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionBundle,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    TimePrecision,
)
from tests.disclosures.dart_fixture import create_fixture_adapter

_TARGET = DartDividendTarget(symbol="005930", corp_code="00126380")


def _fetch(list_filename: str = "list_005930_page1.json") -> CorporateActionBundle:
    async def scenario() -> CorporateActionBundle:
        adapter, _ = create_fixture_adapter(list_filename, _TARGET)
        try:
            return await adapter.fetch_corporate_actions(date(2026, 4, 1), date(2026, 5, 31))
        finally:
            await adapter.close()

    return anyio.run(scenario)


def test_normalizes_cash_dividend_disclosures_in_announcement_order() -> None:
    bundle = _fetch()

    assert bundle.source == "DART"
    assert bundle.symbol == "005930"
    assert len(bundle.observations) == 2
    original, correction = (observation.action for observation in bundle.observations)
    assert original.action_type is CorporateActionType.CASH_DIVIDEND
    assert original.lifecycle is CorporateActionLifecycle.ANNOUNCED
    assert original.quality is CorporateActionQuality.PENDING
    assert original.announced_at is None
    assert original.time_precision is TimePrecision.DATE
    assert original.announcement_date == date(2026, 4, 30)
    assert original.ex_date is None
    assert original.record_date == date(2026, 3, 31)
    assert original.payment_date == date(2026, 5, 29)
    assert original.cash_amount == Decimal(372)
    assert original.currency == "KRW"
    assert original.source == "DART"
    assert original.source_event_id == "20260430800106"
    assert (
        original.source_reference == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260430800106"
    )
    assert original.available_at == original.received_at
    assert correction.source_event_id == "20260501800001"
    assert correction.cash_amount == Decimal(400)
    assert correction.payment_date == date(2026, 6, 5)
    assert correction.record_date == original.record_date


def test_preserves_raw_evidence_without_credentials() -> None:
    bundle = _fetch()

    assert len(bundle.supporting_raw_responses) == 1
    list_raw = bundle.supporting_raw_responses[0]
    assert list_raw.endpoint == "/api/list.json"
    assert list_raw.request_fingerprint == "dart:list:00126380:20260401:20260531:1"
    assert "fixture-dart-key" not in list_raw.payload_json
    document_raw = bundle.observations[0].raw_response
    assert document_raw.endpoint == "/api/document.xml"
    assert document_raw.request_fingerprint == "dart:document:20260430800106"
    envelope = cast("dict[str, str]", json.loads(document_raw.payload_json))
    assert envelope["rcept_no"] == "20260430800106"
    assert envelope["filename"] == "20260430800106.html"
    assert "document_base64" in envelope
    assert "fixture-dart-key" not in document_raw.payload_json


def test_ignores_unrelated_disclosures() -> None:
    bundle = _fetch()

    fetched_events = {observation.action.source_event_id for observation in bundle.observations}
    assert "20260415000123" not in fetched_events


def test_empty_search_result_returns_empty_bundle() -> None:
    bundle = _fetch("list_no_data.json")

    assert bundle.observations == ()
    assert len(bundle.supporting_raw_responses) == 1


def test_unknown_correction_prefix_fails_collection() -> None:
    with pytest.raises(DartContractError):
        _ = _fetch("list_005930_unknown_prefix.json")


def test_received_at_is_recent_utc() -> None:
    bundle = _fetch()

    for observation in bundle.observations:
        assert observation.action.received_at.tzinfo is not None
        assert abs((datetime.now(UTC) - observation.action.received_at).total_seconds()) < 60
