"""주문 이벤트 시퀀스 경합 검증.

실측 결함(2026-08-21): 비상정지가 이벤트를 쓰는 동시에 체결통보 리스너가 취소 확인을
반영해 두 쓰기가 같은 `sequence`를 잡고 유일 제약을 위반했다. 취소는 증권사에 전달됐는데
비상정지 명령이 예외로 끝났다. 비상정지는 사람의 마지막 통제 수단이라 부분 실패를 남기면
안 되므로, 이벤트를 붙이는 경로가 주문 행을 잠가 직렬화하는지 확인한다.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.market_data_statements import instrument_id_for
from auto_stock_trading.adapters.database.trading_order_writes import (
    OrderTransition,
    transition_order,
)
from auto_stock_trading.adapters.database.trading_rows import (
    OrderEventRow,
    OrderPlanRow,
    OrderRow,
)
from auto_stock_trading.adapters.database.trading_store import PostgresTradingStore
from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.orders.models import OrderState
from auto_stock_trading.settings.runtime import Settings

_NOW: Final = datetime(2026, 8, 21, 4, 0, tzinfo=UTC)
_SYMBOL: Final = "900210"
_HOLD_SECONDS: Final = 0.6
_START_GAP_SECONDS: Final = 0.1


async def _seed(engine_url: str, order_id: UUID, plan_id: UUID) -> UUID:
    engine = create_async_engine(engine_url)
    instrument_id = instrument_id_for(
        country="KR",
        exchange="XKRX",
        symbol=_SYMBOL,
        product_type=ProductType.STOCK,
        currency="KRW",
    )
    async with engine.begin() as connection:
        _ = await connection.execute(delete(InstrumentRow).where(InstrumentRow.symbol == _SYMBOL))
        _ = await connection.execute(
            insert(InstrumentRow).values(
                id=instrument_id,
                country="KR",
                exchange="XKRX",
                symbol=_SYMBOL,
                product_type=ProductType.STOCK.value,
                currency="KRW",
                name="테스트경합",
                trading_status="active",
                source="TEST",
                source_as_of=_NOW.date(),
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        _ = await connection.execute(
            insert(OrderPlanRow).values(
                id=plan_id,
                environment="paper",
                strategy_name="lock-test",
                strategy_version="1",
                parameters_json="{}",
                signal_date=_NOW.date(),
                trading_date=_NOW.date(),
                automation_state="running",
                status="created",
                planned_at=_NOW,
                created_at=_NOW,
            )
        )
        _ = await connection.execute(
            insert(OrderRow).values(
                id=order_id,
                plan_id=plan_id,
                client_order_id=f"lock-test-{order_id.hex[:12]}",
                instrument_id=instrument_id,
                sequence=1,
                side="buy",
                order_type="limit",
                quantity=2,
                filled_quantity=0,
                limit_price=Decimal(1000),
                state=OrderState.SUBMITTED.value,
                broker_order_id=f"L{order_id.hex[:9]}",
                broker_org_no="00950",
                submitted_at=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
                revision_count=0,
            )
        )
        _ = await connection.execute(
            insert(OrderEventRow).values(
                id=uuid4(),
                order_id=order_id,
                sequence=1,
                previous_state=None,
                state=OrderState.SUBMITTED.value,
                reason_code="seed",
                occurred_at=_NOW,
            )
        )
    await engine.dispose()
    return instrument_id


async def _cleanup(engine_url: str, plan_id: UUID) -> None:
    engine = create_async_engine(engine_url)
    async with engine.begin() as connection:
        _ = await connection.execute(delete(OrderPlanRow).where(OrderPlanRow.id == plan_id))
        _ = await connection.execute(delete(InstrumentRow).where(InstrumentRow.symbol == _SYMBOL))
    await engine.dispose()


def test_concurrent_event_writers_are_serialized_by_the_order_row_lock() -> None:
    """두 트랜잭션이 같은 주문에 이벤트를 붙일 때 시퀀스가 겹치지 않는다.

    잠금이 없으면 뒤 트랜잭션이 앞 트랜잭션의 커밋을 기다리지 않고 같은 시퀀스를 잡는다.
    """

    async def run() -> None:
        url = Settings().database_url.get_secret_value()
        order_id = uuid4()
        plan_id = uuid4()
        _ = await _seed(url, order_id, plan_id)
        first = create_async_engine(url)
        second = create_async_engine(url)
        finished: list[tuple[str, float]] = []
        try:
            started = anyio.current_time()

            async def holder() -> None:
                sessions = async_sessionmaker(first, expire_on_commit=False)
                async with sessions.begin() as session:
                    await transition_order(
                        session,
                        OrderTransition(
                            order_id=order_id,
                            state=OrderState.PARTIALLY_FILLED,
                            reason_code="holder",
                            occurred_at=_NOW,
                            values={"filled_quantity": 1},
                        ),
                    )
                    # 커밋 전에 붙잡아 두어 두 번째 쓰기가 잠금을 기다리게 만든다.
                    await anyio.sleep(_HOLD_SECONDS)
                finished.append(("holder", anyio.current_time() - started))

            async def waiter() -> None:
                # 비상정지가 쓰는 경로다. 상태를 바꾸지 않으므로 UPDATE로 행이 잠기지 않는다.
                await anyio.sleep(_START_GAP_SECONDS)
                store = PostgresTradingStore(second, async_sessionmaker(second))
                await store.record_order_event(
                    order_id,
                    "waiter",
                    None,
                    _NOW + timedelta(seconds=1),
                )
                finished.append(("waiter", anyio.current_time() - started))

            async with anyio.create_task_group() as tasks:
                _ = tasks.start_soon(holder)
                _ = tasks.start_soon(waiter)

            elapsed = dict(finished)
            # 두 번째 쓰기는 첫 트랜잭션이 커밋한 뒤에야 끝난다.
            assert elapsed["waiter"] >= _HOLD_SECONDS

            reader = create_async_engine(url)
            async with reader.connect() as connection:
                rows = (
                    await connection.execute(
                        select(OrderEventRow.sequence, OrderEventRow.reason_code)
                        .where(OrderEventRow.order_id == order_id)
                        .order_by(OrderEventRow.sequence)
                    )
                ).all()
            await reader.dispose()
            assert [(row[0], row[1]) for row in rows] == [
                (1, "seed"),
                (2, "holder"),
                (3, "waiter"),
            ]
        finally:
            await first.dispose()
            await second.dispose()
            await _cleanup(url, plan_id)

    anyio.run(run)
