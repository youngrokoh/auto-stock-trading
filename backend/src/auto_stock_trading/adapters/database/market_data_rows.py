from datetime import date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


@final
class InstrumentRow(Base):
    __tablename__: str = "instrument"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint(
            "country",
            "exchange",
            "symbol",
            "product_type",
            "currency",
            name="uq_instrument_identity",
        ),
        {"schema": "reference"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(2))
    exchange: Mapped[str] = mapped_column(String(12))
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    product_type: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(160))
    english_name: Mapped[str | None] = mapped_column(String(240))
    listed_on: Mapped[date | None] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)
    trading_status: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(32))
    source_as_of: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@final
class RawApiResponseRow(Base):
    __tablename__: str = "raw_api_response"
    __table_args__: tuple[dict[str, str]] = ({"schema": "operations"},)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(32), index=True)
    endpoint: Mapped[str] = mapped_column(String(240))
    request_fingerprint: Mapped[str] = mapped_column(String(240), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


@final
class QuoteRow(Base):
    __tablename__: str = "quote"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("instrument_id", "source", name="uq_quote_latest_source"),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
        index=True,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    open_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    low_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    previous_close: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    change: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    change_percent: Mapped[Decimal] = mapped_column(Numeric(16, 8))
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[Decimal] = mapped_column(Numeric(32, 8))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.raw_api_response.id"),
    )


@final
class MarketBarRow(Base):
    __tablename__: str = "market_bar"
    __table_args__: tuple[UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint(
            "instrument_id",
            "interval",
            "trading_date",
            "source",
            "version",
            name="uq_market_bar_version",
        ),
        Index(
            "uq_market_bar_current",
            "instrument_id",
            "interval",
            "trading_date",
            "source",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
        index=True,
    )
    interval: Mapped[str] = mapped_column(String(8))
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    open_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    low_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    close_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[Decimal] = mapped_column(Numeric(32, 8))
    adjusted: Mapped[bool] = mapped_column()
    correction_code: Mapped[str | None] = mapped_column(String(80))
    split_ratio: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finality: Mapped[str] = mapped_column(String(16))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.raw_api_response.id"),
    )


@final
class SyncStatusRow(Base):
    __tablename__: str = "api_sync_status"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("source", "operation", "symbol", name="uq_sync_target"),
        {"schema": "operations"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
