from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.fundamental_rows import DisclosureRow
from auto_stock_trading.adapters.database.market_data_corporate_action_store import (
    UnknownInstrumentError,
)
from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_sync_statements import (
    SyncTarget,
    sync_failed,
    sync_started,
    sync_succeeded,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from auto_stock_trading.domain.fundamentals.disclosures import DisclosureBundle
    from auto_stock_trading.domain.fundamentals.financial_statements import (
        FinancialRawResponse,
    )
    from auto_stock_trading.domain.market_data.models import InstrumentTarget

_SOURCE: Final = "DART"
_OPERATION: Final = "disclosures"


@final
class PostgresDisclosureStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresDisclosureStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresDisclosureStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def mark_started(self, target: InstrumentTarget, started_at: datetime) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_started(SyncTarget(_SOURCE, _OPERATION, target.symbol), started_at)
            )

    async def save_disclosure_bundle(self, bundle: DisclosureBundle) -> int:
        async with self._sessions.begin() as session:
            instrument_id = await session.scalar(
                select(InstrumentRow.id).where(InstrumentRow.symbol == bundle.symbol).limit(1)
            )
            if instrument_id is None:
                raise UnknownInstrumentError(bundle.symbol)
            saved = 0
            for page in bundle.pages:
                raw_id = self._add_raw_row(session, page.raw)
                for disclosure in page.disclosures:
                    statement = (
                        insert(DisclosureRow)
                        .values(
                            id=uuid4(),
                            instrument_id=instrument_id,
                            corp_code=disclosure.corp_code,
                            rcept_no=disclosure.rcept_no,
                            report_nm=disclosure.report_nm,
                            flr_nm=disclosure.filer_name,
                            rcept_dt=disclosure.receipt_date,
                            disclosure_type=disclosure.disclosure_type.value,
                            received_at=disclosure.received_at,
                            raw_response_id=raw_id,
                        )
                        .on_conflict_do_nothing(constraint="uq_disclosure_receipt")
                    )
                    inserted = await session.scalar(statement.returning(DisclosureRow.id))
                    saved += 1 if inserted is not None else 0
            _ = await session.execute(
                sync_succeeded(
                    SyncTarget(_SOURCE, _OPERATION, bundle.symbol),
                    bundle.collected_at,
                )
            )
            return saved

    async def mark_failed(
        self,
        target: InstrumentTarget,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._sessions.begin() as session:
            _ = await session.execute(
                sync_failed(
                    SyncTarget(_SOURCE, _OPERATION, target.symbol),
                    failed_at,
                    error_code,
                    error_message,
                )
            )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    def _add_raw_row(session: AsyncSession, raw: FinancialRawResponse) -> UUID:
        raw_id = uuid4()
        session.add(
            RawApiResponseRow(
                id=raw_id,
                source=_SOURCE,
                operation=_OPERATION,
                endpoint=raw.endpoint,
                request_fingerprint=raw.request_fingerprint,
                received_at=raw.received_at,
                payload_json=raw.payload_json,
            )
        )
        return raw_id
