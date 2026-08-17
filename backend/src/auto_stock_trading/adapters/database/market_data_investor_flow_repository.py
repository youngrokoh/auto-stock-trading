from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    InvestorFlowRow,
)
from auto_stock_trading.domain.market_data.investor_flows import VersionedInvestorFlow

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from sqlalchemy.sql import Select

    from auto_stock_trading.domain.market_data.investor_flows import InvestorFlow


@dataclass(frozen=True, slots=True)
class InvestorFlowEvidence:
    flow: InvestorFlow
    instrument_id: UUID
    raw_response_id: UUID


async def save_investor_flow(session: AsyncSession, evidence: InvestorFlowEvidence) -> None:
    flow = evidence.flow
    current = await session.scalar(
        _current_flow_statement(evidence.instrument_id, flow).with_for_update()
    )
    if current is None:
        session.add(_new_flow_row(evidence, 1))
        return
    if _flow_facts_match(current, flow):
        if flow.received_at > current.received_at:
            current.received_at = flow.received_at
            current.raw_response_id = evidence.raw_response_id
        return
    if flow.received_at <= current.received_at:
        return
    current.superseded_at = flow.received_at
    session.add(_new_flow_row(evidence, current.version + 1))


async def read_investor_flows(
    sessions: async_sessionmaker[AsyncSession],
    symbol: str,
    limit: int,
) -> tuple[VersionedInvestorFlow, ...]:
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(InvestorFlowRow)
                .join(InstrumentRow, InvestorFlowRow.instrument_id == InstrumentRow.id)
                .where(
                    InstrumentRow.symbol == symbol,
                    InvestorFlowRow.superseded_at.is_(None),
                )
                .order_by(InvestorFlowRow.trading_date.desc())
                .limit(limit)
            )
        ).all()
    return tuple(
        VersionedInvestorFlow(
            symbol=symbol,
            trading_date=row.trading_date,
            individual_net_quantity=row.individual_net_quantity,
            foreign_net_quantity=row.foreign_net_quantity,
            institution_net_quantity=row.institution_net_quantity,
            individual_net_value=row.individual_net_value,
            foreign_net_value=row.foreign_net_value,
            institution_net_value=row.institution_net_value,
            source=row.source,
            received_at=row.received_at,
            version=row.version,
            valid_from=row.valid_from,
            superseded_at=row.superseded_at,
        )
        for row in rows
    )


def _current_flow_statement(
    instrument_id: UUID,
    flow: InvestorFlow,
) -> Select[tuple[InvestorFlowRow]]:
    return (
        select(InvestorFlowRow)
        .where(
            InvestorFlowRow.instrument_id == instrument_id,
            InvestorFlowRow.trading_date == flow.trading_date,
            InvestorFlowRow.source == flow.source,
            InvestorFlowRow.superseded_at.is_(None),
        )
        .limit(1)
    )


def _flow_facts_match(row: InvestorFlowRow, flow: InvestorFlow) -> bool:
    return (
        row.individual_net_quantity == flow.individual_net_quantity
        and row.foreign_net_quantity == flow.foreign_net_quantity
        and row.institution_net_quantity == flow.institution_net_quantity
        and row.individual_net_value == flow.individual_net_value
        and row.foreign_net_value == flow.foreign_net_value
        and row.institution_net_value == flow.institution_net_value
    )


def _new_flow_row(evidence: InvestorFlowEvidence, version: int) -> InvestorFlowRow:
    flow = evidence.flow
    return InvestorFlowRow(
        id=uuid4(),
        instrument_id=evidence.instrument_id,
        trading_date=flow.trading_date,
        individual_net_quantity=flow.individual_net_quantity,
        foreign_net_quantity=flow.foreign_net_quantity,
        institution_net_quantity=flow.institution_net_quantity,
        individual_net_value=flow.individual_net_value,
        foreign_net_value=flow.foreign_net_value,
        institution_net_value=flow.institution_net_value,
        source=flow.source,
        received_at=flow.received_at,
        version=version,
        valid_from=flow.received_at,
        superseded_at=None,
        raw_response_id=evidence.raw_response_id,
    )
