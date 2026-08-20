"""종목 유니버스 사실 행. `market_data_rows`가 이미 커서 별 모듈로 둔다."""

from datetime import datetime
from typing import final
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class StockProfileRow(Base):
    __tablename__: str = "stock_profile"
    __table_args__: tuple[UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint("symbol", "version", name="uq_stock_profile_version"),
        Index(
            "uq_stock_profile_current",
            "symbol",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        {"schema": "reference"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(9))
    isin: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(80))
    sector_code: Mapped[str] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.raw_api_response.id"),
    )
