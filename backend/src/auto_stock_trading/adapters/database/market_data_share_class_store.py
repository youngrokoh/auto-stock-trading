"""상장 주식종류 사실 저장·조회(유니버스 계약 §주식종류 사실).

`market_data_stock_store`가 이미 300줄을 넘어 별 모듈로 둔다. 우선주에도 `reference.instrument`
행을 만들지만 `stock_profile`에는 넣지 않으므로 유니버스 조회에는 들어오지 않는다.
"""

from __future__ import annotations

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

from auto_stock_trading.adapters.database.market_data_rows import (
    InstrumentRow,
    RawApiResponseRow,
)
from auto_stock_trading.adapters.database.market_data_statements import instrument_id_for
from auto_stock_trading.adapters.database.reference_stock_rows import ShareClassRow
from auto_stock_trading.domain.market_data.models import ProductType
from auto_stock_trading.domain.market_data.share_classes import (
    ShareClass,
    ShareClassGroup,
    ShareClassKind,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from auto_stock_trading.domain.market_data.models import RawBrokerResponse

_SOURCE: Final = "KIS_MASTER"
_COUNTRY: Final = "KR"
_EXCHANGE: Final = "XKRX"
_CURRENCY: Final = "KRW"
_ACTIVE: Final = "active"


@final
class PostgresShareClassStore:
    def __init__(
        self,
        engine: AsyncEngine | None,
        sessions: async_sessionmaker[AsyncSession] | None,
        database_url: str | None = None,
    ) -> None:
        self._engine = engine
        self._sessions_or_none = sessions
        self._database_url = database_url

    @classmethod
    def from_url(cls, database_url: str) -> PostgresShareClassStore:
        """엔진은 첫 사용까지 만들지 않는다.

        `create_app`이 기본 factory로 이 저장소를 만들지만 가치지표를 조회하지 않는 요청·테스트도
        많다. 즉시 엔진을 만들면 쓰지 않는 연결 풀이 열린다 — API 테스트가 앱을 여러 번 만들면서
        연결 한도(실측 max_connections 100)에 부딪혀 다른 통합 테스트가 깨졌다.
        """
        return cls(None, None, database_url)

    @classmethod
    def from_connection(cls, connection: AsyncConnection) -> PostgresShareClassStore:
        sessions = async_sessionmaker(
            connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        return cls(None, sessions)

    @property
    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        sessions = self._sessions_or_none
        if sessions is None:
            url = self._database_url
            if url is None:
                message = "share class store has neither a session factory nor a url"
                raise RuntimeError(message)
            self._engine = create_async_engine(url, pool_pre_ping=True)
            sessions = async_sessionmaker(self._engine, expire_on_commit=False)
            self._sessions_or_none = sessions
        return sessions

    async def save_groups(
        self,
        groups: Sequence[ShareClassGroup],
        raw: RawBrokerResponse,
        received_at: datetime,
    ) -> int:
        """새 버전 수를 돌려준다. 같은 값 재수집은 0이다."""
        async with self._sessions.begin() as session:
            raw_id = uuid4()
            session.add(
                RawApiResponseRow(
                    id=raw_id,
                    source=_SOURCE,
                    operation=raw.operation.value,
                    endpoint=raw.endpoint,
                    request_fingerprint=raw.request_fingerprint,
                    received_at=raw.received_at,
                    payload_json=raw.payload_json,
                )
            )
            saved = 0
            for group in groups:
                for item in group.classes:
                    if await _save_class(
                        session,
                        group.common_symbol,
                        item,
                        received_at,
                        raw_id,
                    ):
                        saved += 1
            return saved

    async def ensure_instrument(self, item: ShareClass, received_at: datetime) -> None:
        """시세를 수집할 종목에만 `reference.instrument` 행을 만든다.

        사실은 KOSPI 전 종목(실측 914)에 대해 저장하지만 종목 행은 **수집 대상만** 만든다.
        전부 만들면 데이터가 하나도 없는 종목이 종목 목록 화면을 채운다(실측 201 → 915).
        """
        async with self._sessions.begin() as session:
            _ = await session.execute(_instrument_upsert(item, received_at, received_at))

    async def share_classes(self, common_symbol: str) -> tuple[ShareClass, ...]:
        """현재 버전 클래스 목록. 사실이 없으면 빈 목록이다(우선주 유무를 모르는 상태)."""
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ShareClassRow)
                    .where(
                        ShareClassRow.common_symbol == common_symbol,
                        ShareClassRow.superseded_at.is_(None),
                    )
                    .order_by(ShareClassRow.class_kind.desc(), ShareClassRow.symbol)
                )
            ).all()
        return tuple(
            ShareClass(
                symbol=row.symbol,
                class_kind=ShareClassKind(row.class_kind),
                isin=row.isin,
                name=row.name,
            )
            for row in rows
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _instrument_upsert(item: ShareClass, received_at: datetime, now: datetime):  # noqa: ANN202
    """우선주도 종목 행이 필요하다. 시세·상장주식수를 종목 단위로 저장하기 때문이다."""
    statement = insert(InstrumentRow).values(
        id=instrument_id_for(
            country=_COUNTRY,
            exchange=_EXCHANGE,
            symbol=item.symbol,
            product_type=ProductType.STOCK,
            currency=_CURRENCY,
        ),
        country=_COUNTRY,
        exchange=_EXCHANGE,
        symbol=item.symbol,
        product_type=ProductType.STOCK.value,
        currency=_CURRENCY,
        name=item.name,
        english_name=None,
        listed_on=None,
        delisted_on=None,
        trading_status=_ACTIVE,
        source=_SOURCE,
        source_as_of=received_at.date(),
        created_at=now,
        updated_at=now,
    )
    return statement.on_conflict_do_update(
        constraint="uq_instrument_identity",
        set_={
            "name": item.name,
            "source": _SOURCE,
            "source_as_of": received_at.date(),
            "updated_at": now,
        },
    )


async def _save_class(
    session: AsyncSession,
    common_symbol: str,
    item: ShareClass,
    received_at: datetime,
    raw_id: UUID,
) -> bool:
    current = await session.scalar(
        select(ShareClassRow)
        .where(
            ShareClassRow.symbol == item.symbol,
            ShareClassRow.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if current is not None and _same_fact(current, common_symbol, item):
        if received_at > current.received_at:
            current.received_at = received_at
            current.raw_response_id = raw_id
        return False
    version = 1
    if current is not None:
        if received_at <= current.received_at:
            return False
        current.superseded_at = received_at
        version = current.version + 1
    session.add(
        ShareClassRow(
            id=uuid4(),
            common_symbol=common_symbol,
            symbol=item.symbol,
            class_kind=item.class_kind.value,
            isin=item.isin,
            name=item.name,
            source=_SOURCE,
            received_at=received_at,
            version=version,
            valid_from=received_at,
            superseded_at=None,
            raw_response_id=raw_id,
        )
    )
    return True


def _same_fact(current: ShareClassRow, common_symbol: str, item: ShareClass) -> bool:
    return (
        current.common_symbol == common_symbol
        and current.class_kind == item.class_kind.value
        and current.isin == item.isin
        and current.name == item.name
    )
