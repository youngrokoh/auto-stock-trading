from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    PostgresCorporateActionStore,
    UnknownInstrumentError,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    CorporateActionRow,
    InstrumentRow,
    RawApiResponseRow,
    SyncStatusRow,
)
from auto_stock_trading.adapters.disclosures.kodex_distributions import KodexDistributionTarget
from auto_stock_trading.adapters.disclosures.opendart_corporate_actions import (
    DartDividendTarget,
)
from auto_stock_trading.application.corporate_actions import CorporateActionCollector
from auto_stock_trading.settings.runtime import Settings
from tests.disclosures.dart_fixture import create_fixture_adapter
from tests.disclosures.kodex_fixture import create_fixture_adapter as create_kodex_adapter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

    from auto_stock_trading.domain.market_data.corporate_actions import CorporateActionBundle

    type Sessions = async_sessionmaker[AsyncSession]
    type CollectionScenario = Callable[[AsyncConnection, Sessions], Awaitable[None]]

_TARGET = DartDividendTarget(symbol="005930", corp_code="00126380")
_ETF_TARGET = KodexDistributionTarget(symbol="069500", fund_id="2ETF01")
_RANGE = (date(2026, 4, 1), date(2026, 5, 31))
_ETF_RANGE = (date(2026, 1, 1), date(2026, 8, 17))
_STARTED_AT = datetime(2026, 8, 16, 2, 0, tzinfo=UTC)


def test_collection_persists_versions_raw_evidence_and_success_status() -> None:
    async def scenario(connection: AsyncConnection, sessions: Sessions) -> None:
        # Given
        await _add_instrument(sessions)

        # When
        bundle = await _collect(connection)

        # Then
        actions = await _action_rows(sessions)
        raws = await _raw_rows(sessions)
        status = await _sync_row(sessions)
        assert len(bundle.observations) == 2
        assert tuple(row.version for row in actions) == (1, 2)
        assert len({row.action_key for row in actions}) == 1
        assert actions[0].cash_amount == Decimal(372)
        assert actions[0].superseded_at is not None
        assert actions[1].cash_amount == Decimal(400)
        assert actions[1].payment_date == date(2026, 6, 5)
        assert actions[1].superseded_at is None
        assert len(raws) == 3
        assert {raw.operation for raw in raws} == {"corporate_actions"}
        assert {raw.source for raw in raws} == {"DART"}
        assert status is not None
        assert status.state == "success"

    anyio.run(_run_scenario, scenario)


def test_repeated_collection_does_not_create_versions_but_appends_raw_evidence() -> None:
    async def scenario(connection: AsyncConnection, sessions: Sessions) -> None:
        # Given
        await _add_instrument(sessions)
        _ = await _collect(connection)

        # When
        _ = await _collect(connection)

        # Then
        actions = await _action_rows(sessions)
        raws = await _raw_rows(sessions)
        assert tuple(row.version for row in actions) == (1, 2)
        assert len(raws) == 6

    anyio.run(_run_scenario, scenario)


def test_kodex_distribution_collection_persists_confirmed_facts() -> None:
    async def scenario(connection: AsyncConnection, sessions: Sessions) -> None:
        # Given
        await _add_instrument(sessions, _ETF_TARGET.symbol, "etf", "KODEX 200")

        # When
        bundle = await _collect_kodex(connection)

        # Then
        actions = await _action_rows(sessions, _ETF_TARGET.symbol)
        raws = await _raw_rows(sessions, "KODEX")
        status = await _sync_row(sessions, "KODEX", _ETF_TARGET.symbol)
        assert len(bundle.observations) == 3
        assert tuple(row.version for row in actions) == (1, 1, 1)
        assert len({row.action_key for row in actions}) == 3
        assert {row.action_type for row in actions} == {"etf_distribution"}
        assert {row.lifecycle_status for row in actions} == {"confirmed"}
        assert tuple(row.cash_amount for row in actions) == (
            Decimal(80),
            Decimal(446),
            Decimal(183),
        )
        assert len(raws) == 1
        assert status is not None
        assert status.state == "success"

    anyio.run(_run_scenario, scenario)


def test_repeated_kodex_collection_reuses_versions_and_appends_raw_evidence() -> None:
    async def scenario(connection: AsyncConnection, sessions: Sessions) -> None:
        # Given
        await _add_instrument(sessions, _ETF_TARGET.symbol, "etf", "KODEX 200")
        _ = await _collect_kodex(connection)

        # When
        _ = await _collect_kodex(connection)

        # Then
        actions = await _action_rows(sessions, _ETF_TARGET.symbol)
        raws = await _raw_rows(sessions, "KODEX")
        assert tuple(row.version for row in actions) == (1, 1, 1)
        assert len(raws) == 2

    anyio.run(_run_scenario, scenario)


def test_missing_instrument_fails_collection_and_records_failure() -> None:
    async def scenario(connection: AsyncConnection, sessions: Sessions) -> None:
        # Given
        await _remove_instrument(sessions)

        # When
        with pytest.raises(UnknownInstrumentError):
            _ = await _collect(connection)

        # Then
        status = await _sync_row(sessions)
        assert status is not None
        assert status.state == "failed"
        assert status.error_code == "UnknownInstrumentError"

    anyio.run(_run_scenario, scenario)


async def _run_scenario(scenario: CollectionScenario) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    async with engine.connect() as connection:
        transaction = await connection.begin()
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            await scenario(connection, sessions)
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _collect(connection: AsyncConnection) -> CorporateActionBundle:
    adapter, _ = create_fixture_adapter(target=_TARGET)
    store = PostgresCorporateActionStore.from_connection(connection)
    collector = CorporateActionCollector(source=adapter, store=store)
    try:
        return await collector.collect(_RANGE[0], _RANGE[1], _STARTED_AT)
    finally:
        await adapter.close()
        await store.close()


async def _collect_kodex(connection: AsyncConnection) -> CorporateActionBundle:
    adapter, _ = create_kodex_adapter(target=_ETF_TARGET)
    store = PostgresCorporateActionStore.from_connection(connection)
    collector = CorporateActionCollector(source=adapter, store=store)
    try:
        return await collector.collect(_ETF_RANGE[0], _ETF_RANGE[1], _STARTED_AT)
    finally:
        await adapter.close()
        await store.close()


async def _remove_instrument(sessions: Sessions, symbol: str = _TARGET.symbol) -> None:
    async with sessions.begin() as session:
        _ = await session.execute(delete(InstrumentRow).where(InstrumentRow.symbol == symbol))
        _ = await session.execute(
            delete(CorporateActionRow).where(CorporateActionRow.source.in_(("DART", "KODEX")))
        )
        _ = await session.execute(
            delete(RawApiResponseRow).where(RawApiResponseRow.source.in_(("DART", "KODEX")))
        )


async def _add_instrument(
    sessions: Sessions,
    symbol: str = _TARGET.symbol,
    product_type: str = "stock",
    name: str = "삼성전자",
) -> None:
    await _remove_instrument(sessions, symbol)
    async with sessions.begin() as session:
        session.add(
            InstrumentRow(
                id=uuid4(),
                country="KR",
                exchange="XKRX",
                symbol=symbol,
                product_type=product_type,
                currency="KRW",
                name=name,
                english_name=None,
                listed_on=None,
                delisted_on=None,
                trading_status="trading",
                source="KIS",
                source_as_of=date(2026, 8, 16),
                created_at=_STARTED_AT,
                updated_at=_STARTED_AT,
            )
        )


async def _action_rows(
    sessions: Sessions,
    symbol: str = _TARGET.symbol,
) -> tuple[CorporateActionRow, ...]:
    async with sessions() as session:
        return tuple(
            (
                await session.scalars(
                    select(CorporateActionRow)
                    .join(InstrumentRow, CorporateActionRow.instrument_id == InstrumentRow.id)
                    .where(InstrumentRow.symbol == symbol)
                    .order_by(CorporateActionRow.record_date, CorporateActionRow.version)
                )
            ).all()
        )


async def _raw_rows(
    sessions: Sessions,
    source: str = "DART",
) -> tuple[RawApiResponseRow, ...]:
    async with sessions() as session:
        return tuple(
            (
                await session.scalars(
                    select(RawApiResponseRow).where(RawApiResponseRow.source == source)
                )
            ).all()
        )


async def _sync_row(
    sessions: Sessions,
    source: str = "DART",
    symbol: str = _TARGET.symbol,
) -> SyncStatusRow | None:
    async with sessions() as session:
        return await session.scalar(
            select(SyncStatusRow).where(
                SyncStatusRow.source == source,
                SyncStatusRow.operation == "corporate_actions",
                SyncStatusRow.symbol == symbol,
            )
        )
