from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.database.fundamental_disclosure_reader import (
    PostgresDisclosureReader,
)
from auto_stock_trading.adapters.database.fundamental_disclosure_store import (
    PostgresDisclosureStore,
)
from auto_stock_trading.adapters.database.fundamental_rows import DisclosureRow
from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.domain.fundamentals.disclosures import (
    Disclosure,
    DisclosureBundle,
    DisclosurePage,
    DisclosureType,
)
from auto_stock_trading.domain.fundamentals.financial_statements import (
    FinancialRawResponse,
)
from auto_stock_trading.settings.runtime import Settings

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

_NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def _disclosure(rcept_no: str, receipt_date: date, disclosure_type: DisclosureType) -> Disclosure:
    return Disclosure(
        symbol="005930",
        corp_code="00126380",
        rcept_no=rcept_no,
        report_nm="사업보고서 (2025.12)",
        filer_name="삼성전자",
        receipt_date=receipt_date,
        disclosure_type=disclosure_type,
        received_at=_NOW,
    )


def _bundle(disclosures: tuple[Disclosure, ...]) -> DisclosureBundle:
    raw = FinancialRawResponse(
        endpoint="/api/list.json",
        request_fingerprint="dart:disclosures:00126380:A:20250817:20260817:1",
        received_at=_NOW,
        payload_json='{"status":"000"}',
    )
    return DisclosureBundle(
        symbol="005930",
        corp_code="00126380",
        pages=(DisclosurePage(raw=raw, disclosures=disclosures),),
        collected_at=_NOW,
    )


def test_disclosure_facts_are_idempotent_and_ordered() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresDisclosureStore.from_connection(connection)
            reader = PostgresDisclosureReader.from_connection(connection)
            try:
                instrument_id = await _ensure_instrument(connection, "005930")
                _ = await connection.execute(
                    delete(DisclosureRow).where(DisclosureRow.instrument_id == instrument_id)
                )

                first = _bundle(
                    (
                        _disclosure("20260310002820", date(2026, 3, 10), DisclosureType.PERIODIC),
                        _disclosure("20260811000285", date(2026, 8, 11), DisclosureType.OWNERSHIP),
                    )
                )
                assert await store.save_disclosure_bundle(first) == 2
                assert await store.save_disclosure_bundle(first) == 0

                extended = _bundle(
                    (
                        _disclosure("20260310002820", date(2026, 3, 10), DisclosureType.PERIODIC),
                        _disclosure("20260814003699", date(2026, 8, 14), DisclosureType.PERIODIC),
                    )
                )
                assert await store.save_disclosure_bundle(extended) == 1

                disclosures = await reader.read_disclosures("005930", 10)
                assert [entry.rcept_no for entry in disclosures] == [
                    "20260814003699",
                    "20260811000285",
                    "20260310002820",
                ]
                assert disclosures[0].disclosure_type is DisclosureType.PERIODIC
                assert disclosures[1].filer_name == "삼성전자"
            finally:
                await store.close()
                await reader.close()
                await transaction.rollback()
        await engine.dispose()

    anyio.run(run)


async def _ensure_instrument(connection: AsyncConnection, symbol: str) -> UUID:
    existing = await connection.scalar(
        select(InstrumentRow.id).where(InstrumentRow.symbol == symbol).limit(1)
    )
    if existing is not None:
        return existing
    instrument_id = uuid4()
    _ = await connection.execute(
        insert(InstrumentRow).values(
            id=instrument_id,
            country="KR",
            exchange="XKRX",
            symbol=symbol,
            product_type="stock",
            currency="KRW",
            name="CI 검증 종목",
            english_name=None,
            listed_on=None,
            delisted_on=None,
            trading_status="trading",
            source="KIS",
            source_as_of=date(2026, 8, 17),
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return instrument_id
