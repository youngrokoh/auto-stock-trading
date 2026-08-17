from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import anyio
import pytest

from auto_stock_trading.adapters.disclosures.kodex_distributions import KodexContractError
from auto_stock_trading.domain.market_data.corporate_actions import (
    CorporateActionBundle,
    CorporateActionLifecycle,
    CorporateActionQuality,
    CorporateActionType,
    TimePrecision,
)
from tests.disclosures.kodex_fixture import create_fixture_adapter

_SEOUL = ZoneInfo("Asia/Seoul")


def _fetch(fixture_filename: str = "divid_info_2ETF01.json") -> CorporateActionBundle:
    async def scenario() -> CorporateActionBundle:
        adapter, _ = create_fixture_adapter(fixture_filename)
        try:
            return await adapter.fetch_corporate_actions(date(2026, 1, 1), date(2026, 8, 17))
        finally:
            await adapter.close()

    return anyio.run(scenario)


def test_normalizes_distributions_within_range_in_record_date_order() -> None:
    bundle = _fetch()

    assert bundle.source == "KODEX"
    assert bundle.symbol == "069500"
    assert tuple(item.action.record_date for item in bundle.observations) == (
        date(2026, 1, 30),
        date(2026, 4, 30),
        date(2026, 7, 31),
    )
    april = bundle.observations[1].action
    assert april.action_type is CorporateActionType.ETF_DISTRIBUTION
    assert april.lifecycle is CorporateActionLifecycle.CONFIRMED
    assert april.quality is CorporateActionQuality.PENDING
    assert april.announced_at is None
    assert april.time_precision is TimePrecision.DATE
    assert april.announcement_date == april.received_at.astimezone(_SEOUL).date()
    assert april.ex_date is None
    assert april.payment_date == date(2026, 5, 6)
    assert april.cash_amount == Decimal(446)
    assert april.currency == "KRW"
    assert april.source == "KODEX"
    assert april.source_event_id == "2ETF01:20260430"
    assert april.source_reference == "https://www.samsungfund.com/etf/product/view.do?id=2ETF01"
    assert april.available_at == april.received_at
    assert abs((datetime.now(UTC) - april.received_at).total_seconds()) < 60


def test_observations_share_one_raw_response_without_duplication() -> None:
    bundle = _fetch()

    assert bundle.supporting_raw_responses == ()
    raws = {id(item.raw_response) for item in bundle.observations}
    assert len(raws) == 1
    raw = bundle.observations[0].raw_response
    assert raw.endpoint == "/api/v1/kodex/divid-info.do"
    assert raw.request_fingerprint == "kodex:distributions:2ETF01"
    assert '"basicD": "20260430"' in raw.payload_json or "20260430" in raw.payload_json


def test_range_excludes_distributions_outside_the_query() -> None:
    bundle = _fetch()

    record_dates = {item.action.record_date for item in bundle.observations}
    assert date(2025, 10, 31) not in record_dates
    assert date(2025, 7, 31) not in record_dates


def test_malformed_amount_fails_collection() -> None:
    with pytest.raises(KodexContractError):
        _ = _fetch("divid_info_bad_amount.json")


def test_unknown_entry_field_fails_collection() -> None:
    with pytest.raises(KodexContractError):
        _ = _fetch("divid_info_extra_field.json")


def test_duplicate_record_date_fails_collection() -> None:
    with pytest.raises(KodexContractError):
        _ = _fetch("divid_info_duplicate.json")
