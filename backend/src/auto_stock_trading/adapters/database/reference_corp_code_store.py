"""DART 고유번호 매핑 저장소. 유니버스 종목만 배당 수집 대상으로 돌려준다."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from auto_stock_trading.adapters.database.market_data_rows import RawApiResponseRow
from auto_stock_trading.adapters.database.reference_stock_rows import (
    DartCorpCodeRow,
    StockProfileRow,
)
from auto_stock_trading.domain.market_data.corp_codes import DartCorpCode

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

    from auto_stock_trading.domain.market_data.corp_codes import DartCorpCodeBundle

_SOURCE: Final = "DART"
_OPERATION: Final = "corp_codes"


@final
class PostgresCorpCodeStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessions = sessions

    @classmethod
    def from_url(cls, database_url: str) -> PostgresCorpCodeStore:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresCorpCodeStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    async def save_corp_codes(self, bundle: DartCorpCodeBundle) -> int:
        """새 버전 수를 돌려준다. 같은 매핑 재수집은 0이다."""
        async with self._sessions.begin() as session:
            raw_id = uuid4()
            session.add(
                RawApiResponseRow(
                    id=raw_id,
                    source=_SOURCE,
                    operation=_OPERATION,
                    endpoint=bundle.raw.endpoint,
                    request_fingerprint=bundle.raw.request_fingerprint,
                    received_at=bundle.raw.received_at,
                    payload_json=bundle.raw.payload_json,
                )
            )
            saved = 0
            for code in bundle.codes:
                if await _save_code(session, code, raw_id):
                    saved += 1
            return saved

    async def universe_symbols(self) -> tuple[str, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(StockProfileRow.symbol)
                .where(StockProfileRow.superseded_at.is_(None))
                .order_by(StockProfileRow.symbol)
            )
            return tuple(rows.all())

    async def universe_corp_codes(self) -> tuple[DartCorpCode, ...]:
        """유니버스에 있고 매핑도 있는 종목만. 둘 중 하나가 없으면 대상이 아니다."""
        statement = (
            select(DartCorpCodeRow)
            .join(StockProfileRow, StockProfileRow.symbol == DartCorpCodeRow.symbol)
            .where(
                DartCorpCodeRow.superseded_at.is_(None),
                StockProfileRow.superseded_at.is_(None),
            )
            .order_by(DartCorpCodeRow.symbol)
        )
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(_corp_code(row) for row in rows)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


async def _save_code(session: AsyncSession, code: DartCorpCode, raw_id: UUID) -> bool:
    current = await session.scalar(
        select(DartCorpCodeRow)
        .where(
            DartCorpCodeRow.symbol == code.symbol,
            DartCorpCodeRow.superseded_at.is_(None),
        )
        .with_for_update()
    )
    same = (
        current is not None
        and current.corp_code == code.corp_code
        and current.corp_name == code.corp_name
    )
    if current is not None and same:
        if code.received_at > current.received_at:
            current.received_at = code.received_at
            current.raw_response_id = raw_id
        return False
    version = 1
    if current is not None:
        if code.received_at <= current.received_at:
            return False
        current.superseded_at = code.received_at
        version = current.version + 1
    session.add(
        DartCorpCodeRow(
            id=uuid4(),
            symbol=code.symbol,
            corp_code=code.corp_code,
            corp_name=code.corp_name,
            source=code.source,
            received_at=code.received_at,
            version=version,
            valid_from=code.received_at,
            superseded_at=None,
            raw_response_id=raw_id,
        )
    )
    return True


def _corp_code(row: DartCorpCodeRow) -> DartCorpCode:
    return DartCorpCode(
        symbol=row.symbol,
        corp_code=row.corp_code,
        corp_name=row.corp_name,
        source=row.source,
        received_at=row.received_at,
    )
