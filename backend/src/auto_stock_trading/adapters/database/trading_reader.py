from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import InstrumentRow
from auto_stock_trading.adapters.database.trading_queries import (
    buy_amount_query,
    consecutive_rejects,
    max_order_amount_query,
    open_orders_query,
    order_attempts_query,
    recent_states_query,
)
from auto_stock_trading.adapters.database.trading_rows import (
    AccountPositionRow,
    AccountSnapshotRow,
    AutomationEventRow,
    AutomationStateRow,
    OrderPlanRow,
    OrderRow,
    RiskDecisionRow,
)
from auto_stock_trading.domain.orders.account import AccountPosition, AccountSnapshot
from auto_stock_trading.domain.orders.models import (
    AutomationState,
    OrderSide,
    OrderState,
    OrderType,
)
from auto_stock_trading.domain.orders.records import (
    AutomationEventRecord,
    AutomationRecord,
    OrderListEntry,
    OrderPlanRecord,
    OrderPlanSummary,
    OrderRecord,
    StoredAccountSnapshot,
    StoredCounters,
    TradingRiskState,
)
from auto_stock_trading.domain.risk.engine import RiskDecision
from auto_stock_trading.domain.risk.limits import RiskRule

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

_API_FAILURE: Final = "api_failure"


def _won(value: Decimal) -> Decimal:
    """asyncpg가 trailing zero numeric을 지수 표기로 돌려주므로 정수 표기로 정규화한다."""
    return value.quantize(Decimal(1))


def _snapshot(
    row: AccountSnapshotRow,
    positions: tuple[AccountPosition, ...],
) -> StoredAccountSnapshot:
    return StoredAccountSnapshot(
        snapshot_id=row.id,
        snapshot=AccountSnapshot(
            source=row.source,
            environment=row.environment,
            account_reference=row.account_reference,
            currency=row.currency,
            cash_balance=_won(row.cash_balance),
            orderable_cash=_won(row.orderable_cash),
            position_value=_won(row.position_value),
            nav=_won(row.nav),
            broker_net_asset=_won(row.broker_net_asset),
            trading_date=row.trading_date,
            as_of=row.as_of,
            received_at=row.received_at,
            positions=positions,
        ),
    )


def _plan(row: OrderPlanRow, orders: tuple[OrderRecord, ...]) -> OrderPlanRecord:
    return OrderPlanRecord(
        plan_id=row.id,
        environment=row.environment,
        strategy_name=row.strategy_name,
        strategy_version=row.strategy_version,
        parameters_json=row.parameters_json,
        signal_date=row.signal_date,
        trading_date=row.trading_date,
        account_snapshot_id=row.account_snapshot_id,
        nav_basis=None if row.nav_basis is None else _won(row.nav_basis),
        session_open_nav=None if row.session_open_nav is None else _won(row.session_open_nav),
        automation_state=AutomationState(row.automation_state),
        status=row.status,
        block_code=row.block_code,
        planned_at=row.planned_at,
        orders=orders,
    )


def _order(
    row: OrderRow,
    symbol: str,
    decisions: tuple[RiskDecision, ...],
) -> OrderRecord:
    return OrderRecord(
        client_order_id=row.client_order_id,
        sequence=row.sequence,
        symbol=symbol,
        side=OrderSide(row.side),
        order_type=OrderType(row.order_type),
        quantity=row.quantity,
        limit_price=row.limit_price,
        reference_price=row.reference_price,
        reference_source=row.reference_source,
        reference_received_at=row.reference_received_at,
        state=OrderState(row.state),
        reject_code=row.reject_code,
        decisions=decisions,
    )


@final
class PostgresTradingReader:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresTradingReader:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresTradingReader:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def automation(self, environment: str) -> AutomationRecord | None:
        statement = select(AutomationStateRow).where(AutomationStateRow.environment == environment)
        async with self._sessions() as session:
            row = await session.scalar(statement)
        if row is None:
            return None
        return AutomationRecord(
            environment=row.environment,
            state=AutomationState(row.state),
            reason_code=row.reason_code,
            trading_date=row.trading_date,
            changed_at=row.changed_at,
        )

    async def automation_events(
        self,
        environment: str,
        limit: int,
    ) -> tuple[AutomationEventRecord, ...]:
        statement = (
            select(AutomationEventRow)
            .where(AutomationEventRow.environment == environment)
            .order_by(AutomationEventRow.occurred_at.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(
            AutomationEventRecord(
                event_type=row.event_type,
                previous_state=(
                    None if row.previous_state is None else AutomationState(row.previous_state)
                ),
                state=None if row.state is None else AutomationState(row.state),
                reason_code=row.reason_code,
                detail=row.detail,
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def account_snapshots(
        self,
        environment: str,
        limit: int,
    ) -> tuple[StoredAccountSnapshot, ...]:
        statement = (
            select(AccountSnapshotRow)
            .where(AccountSnapshotRow.environment == environment)
            .order_by(AccountSnapshotRow.received_at.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            positions = [await _positions(session, row.id) for row in rows]
        return tuple(_snapshot(row, held) for row, held in zip(rows, positions, strict=True))

    async def order_plans(self, environment: str, limit: int) -> tuple[OrderPlanSummary, ...]:
        statement = (
            select(OrderPlanRow)
            .where(OrderPlanRow.environment == environment)
            .order_by(OrderPlanRow.planned_at.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            summaries: list[OrderPlanSummary] = []
            for row in rows:
                states = (
                    await session.scalars(select(OrderRow.state).where(OrderRow.plan_id == row.id))
                ).all()
                summaries.append(
                    OrderPlanSummary(
                        plan=_plan(row, ()),
                        order_count=len(states),
                        rejected_count=sum(
                            1 for state in states if state == OrderState.REJECTED.value
                        ),
                    )
                )
        return tuple(summaries)

    async def order_plan(self, plan_id: UUID) -> OrderPlanRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(select(OrderPlanRow).where(OrderPlanRow.id == plan_id))
            if row is None:
                return None
            order_rows = (
                (
                    await session.execute(
                        select(OrderRow, InstrumentRow.symbol)
                        .join(InstrumentRow, OrderRow.instrument_id == InstrumentRow.id)
                        .where(OrderRow.plan_id == plan_id)
                        .order_by(OrderRow.sequence)
                    )
                )
                .tuples()
                .all()
            )
            orders: list[OrderRecord] = []
            for order_row, symbol in order_rows:
                decisions = await _decisions(session, order_row.id)
                orders.append(_order(order_row, symbol, decisions))
        return _plan(row, tuple(orders))

    async def orders(self, environment: str, limit: int) -> tuple[OrderListEntry, ...]:
        statement = (
            select(OrderRow, InstrumentRow.symbol, OrderPlanRow.trading_date)
            .join(OrderPlanRow, OrderRow.plan_id == OrderPlanRow.id)
            .join(InstrumentRow, OrderRow.instrument_id == InstrumentRow.id)
            .where(OrderPlanRow.environment == environment)
            .order_by(OrderRow.created_at.desc(), OrderRow.sequence.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            rows = (await session.execute(statement)).tuples().all()
        return tuple(_entry(row, symbol, trading_date) for row, symbol, trading_date in rows)

    async def risk_state(
        self,
        environment: str,
        api_failure_window_seconds: int,
    ) -> TradingRiskState:
        evaluated_at = datetime.now(UTC)
        since = evaluated_at - timedelta(seconds=api_failure_window_seconds)
        snapshots = await self.account_snapshots(environment, 1)
        snapshot = snapshots[0] if snapshots else None
        async with self._sessions() as session:
            basis_date = (
                snapshot.snapshot.trading_date
                if snapshot is not None
                else await _latest_plan_date(session, environment)
            )
            baselines = await _nav_baselines(session, environment, basis_date)
            counters = await _counters(session, environment, basis_date)
            failures = await session.scalar(
                select(func.count())
                .select_from(AutomationEventRow)
                .where(
                    AutomationEventRow.environment == environment,
                    AutomationEventRow.event_type == _API_FAILURE,
                    AutomationEventRow.occurred_at >= since,
                )
            )
        session_open_nav, peak_nav, max_order_amount = baselines
        return TradingRiskState(
            evaluated_at=evaluated_at,
            basis_date=basis_date,
            snapshot=snapshot,
            session_open_nav=session_open_nav,
            peak_nav=peak_nav,
            max_order_amount=max_order_amount,
            counters=counters,
            api_failures=failures or 0,
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _entry(row: OrderRow, symbol: str, trading_date: date) -> OrderListEntry:
    return OrderListEntry(
        client_order_id=row.client_order_id,
        plan_id=row.plan_id,
        trading_date=trading_date,
        created_at=row.created_at,
        sequence=row.sequence,
        symbol=symbol,
        side=OrderSide(row.side),
        order_type=OrderType(row.order_type),
        quantity=row.quantity,
        filled_quantity=row.filled_quantity,
        limit_price=row.limit_price,
        reference_price=row.reference_price,
        reference_source=row.reference_source,
        reference_received_at=row.reference_received_at,
        state=OrderState(row.state),
        reject_code=row.reject_code,
        broker_order_id=row.broker_order_id,
        submitted_at=row.submitted_at,
        average_fill_price=row.average_fill_price,
    )


async def _latest_plan_date(session: AsyncSession, environment: str) -> date | None:
    return await session.scalar(
        select(func.max(OrderPlanRow.trading_date)).where(OrderPlanRow.environment == environment)
    )


async def _nav_baselines(
    session: AsyncSession,
    environment: str,
    basis_date: date | None,
) -> tuple[Decimal | None, Decimal | None, Decimal]:
    """장 시작 NAV·고점 NAV·그 거래일 최대 주문 금액. 기준 거래일이 없으면 값을 만들지 않는다."""
    peak = await session.scalar(
        select(func.max(AccountSnapshotRow.nav)).where(
            AccountSnapshotRow.environment == environment
        )
    )
    if basis_date is None:
        return (None, None, Decimal(0))
    session_open = await session.scalar(
        select(AccountSnapshotRow.nav)
        .where(
            AccountSnapshotRow.environment == environment,
            AccountSnapshotRow.trading_date == basis_date,
        )
        .order_by(AccountSnapshotRow.received_at)
        .limit(1)
    )
    largest = await session.scalar(max_order_amount_query(environment, basis_date))
    return (
        None if session_open is None else _won(session_open),
        None if peak is None else _won(peak),
        Decimal(largest or 0),
    )


async def _counters(
    session: AsyncSession,
    environment: str,
    basis_date: date | None,
) -> StoredCounters:
    open_orders = await session.scalar(open_orders_query(environment)) or 0
    attempts = 0
    buy_amount = Decimal(0)
    if basis_date is not None:
        attempts = await session.scalar(order_attempts_query(environment, basis_date)) or 0
        buy_amount = Decimal(await session.scalar(buy_amount_query(environment, basis_date)) or 0)
    states = (await session.scalars(recent_states_query(environment))).all()
    return StoredCounters(
        open_orders=open_orders,
        daily_order_attempts=attempts,
        daily_buy_amount=buy_amount,
        consecutive_rejects=consecutive_rejects(states),
        unreconciled_orders=bool(open_orders),
    )


async def _positions(session: AsyncSession, snapshot_id: UUID) -> tuple[AccountPosition, ...]:
    rows: Sequence[tuple[AccountPositionRow, str]] = (
        (
            await session.execute(
                select(AccountPositionRow, InstrumentRow.symbol)
                .join(InstrumentRow, AccountPositionRow.instrument_id == InstrumentRow.id)
                .where(AccountPositionRow.snapshot_id == snapshot_id)
                .order_by(InstrumentRow.symbol)
            )
        )
        .tuples()
        .all()
    )
    return tuple(
        AccountPosition(
            symbol=symbol,
            quantity=row.quantity,
            orderable_quantity=row.orderable_quantity,
            average_price=row.average_price,
            current_price=row.current_price,
            evaluation_amount=_won(row.evaluation_amount),
            profit_loss=_won(row.profit_loss),
        )
        for row, symbol in rows
    )


async def _decisions(session: AsyncSession, order_id: UUID) -> tuple[RiskDecision, ...]:
    rows = (
        await session.scalars(
            select(RiskDecisionRow)
            .where(RiskDecisionRow.order_id == order_id)
            .order_by(RiskDecisionRow.rule_code)
        )
    ).all()
    return tuple(
        RiskDecision(
            rule=RiskRule(row.rule_code),
            limit_value=Decimal(row.limit_value),
            projected_value=Decimal(row.projected_value),
            passed=row.passed,
        )
        for row in rows
    )
