from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from auto_stock_trading.adapters.brokers.kis_investor_flows import KisInvestorFlowAdapter
from auto_stock_trading.adapters.database.market_data_investor_flow_store import (
    PostgresInvestorFlowStore,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    InvestorFlowRow,
)
from auto_stock_trading.application.investor_flows import InvestorFlowCollector
from auto_stock_trading.domain.market_data.models import InstrumentTarget, ProductType
from auto_stock_trading.settings.runtime import Settings
from tests.brokers.kis_fixture import create_fixture_handler_client

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection

_TARGET = InstrumentTarget("005930", ProductType.STOCK)
_NOW = datetime(2026, 8, 17, 1, 0, tzinfo=UTC)


def test_investor_flows_are_versioned_and_idempotent() -> None:
    async def run() -> None:
        settings = Settings()
        engine = create_async_engine(settings.database_url.get_secret_value())
        client, _ = create_fixture_handler_client()
        adapter = KisInvestorFlowAdapter(client)
        async with engine.connect() as connection:
            transaction = await connection.begin()
            store = PostgresInvestorFlowStore.from_connection(connection)
            collector = InvestorFlowCollector(adapter, store)
            try:
                instrument_id = await _ensure_instrument(connection, _TARGET.symbol)
                _ = await connection.execute(
                    delete(InvestorFlowRow).where(InvestorFlowRow.instrument_id == instrument_id)
                )

                first = await collector.collect(_TARGET, _NOW)
                second = await collector.collect(_TARGET, _NOW)
                assert first.collected == 3
                assert second.collected == 3

                flows = await store.investor_flows(_TARGET.symbol, 10)
                assert len(flows) == 3
                assert all(flow.version == 1 for flow in flows)
                assert flows[0].trading_date.isoformat() == "2026-08-14"
                assert flows[0].foreign_net_quantity == 4913433
                assert flows[0].individual_net_value == -829332

                # 값 변경 관측은 이전 버전을 보존한 새 버전이 된다
                bundle = await adapter.fetch_flows(_TARGET, _NOW)
                later = bundle.flows[0].received_at + timedelta(hours=1)
                corrected = replace(
                    bundle,
                    flows=(
                        replace(
                            bundle.flows[0],
                            foreign_net_quantity=4913000,
                            received_at=later,
                        ),
                    ),
                    collected_at=later,
                )
                await store.save_flow_bundle(corrected)

                current = (await store.investor_flows(_TARGET.symbol, 1))[0]
                assert current.foreign_net_quantity == 4913000
                assert current.version == 2
                versions = (
                    await connection.execute(
                        select(InvestorFlowRow.version, InvestorFlowRow.superseded_at)
                        .where(
                            InvestorFlowRow.instrument_id == instrument_id,
                            InvestorFlowRow.trading_date == flows[0].trading_date,
                        )
                        .order_by(InvestorFlowRow.version)
                    )
                ).all()
                assert [row[0] for row in versions] == [1, 2]
                assert versions[0][1] is not None
                assert versions[1][1] is None
            finally:
                await adapter.close()
                await store.close()
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
