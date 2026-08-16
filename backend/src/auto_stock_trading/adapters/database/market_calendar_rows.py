from datetime import date, datetime
from typing import final
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class MarketCalendarRow(Base):
    __tablename__: str = "market_calendar"
    __table_args__: tuple[UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint(
            "country",
            "exchange",
            "trading_date",
            "session_type",
            "version",
            name="uq_market_calendar_version",
        ),
        Index(
            "uq_market_calendar_current",
            "country",
            "exchange",
            "trading_date",
            "session_type",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        {"schema": "reference"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(2))
    exchange: Mapped[str] = mapped_column(String(12))
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    session_type: Mapped[str] = mapped_column(String(16))
    session_status: Mapped[str] = mapped_column(String(16))
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exchange_timezone: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(240))
    source: Mapped[str] = mapped_column(String(32))
    source_reference: Mapped[str] = mapped_column(String(240))
    source_as_of: Mapped[date] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verification_state: Mapped[str] = mapped_column(String(16))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(ForeignKey("operations.raw_api_response.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
