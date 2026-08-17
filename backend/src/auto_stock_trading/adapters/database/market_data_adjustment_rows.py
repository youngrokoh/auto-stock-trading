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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class AdjustmentDatasetRow(Base):
    __tablename__: str = "adjustment_dataset"
    __table_args__: tuple[Index, dict[str, str]] = (
        Index(
            "uq_adjustment_dataset_inputs",
            "instrument_id",
            "interval",
            "method",
            "range_start",
            "price_cutoff_date",
            "knowledge_cutoff_at",
            "algorithm_version",
            "input_bar_version_hash",
            "action_version_hash",
            unique=True,
            postgresql_where=text("status IN ('building', 'published')"),
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
        index=True,
    )
    interval: Mapped[str] = mapped_column(String(8))
    method: Mapped[str] = mapped_column(String(24))
    range_start: Mapped[date] = mapped_column(Date)
    price_cutoff_date: Mapped[date] = mapped_column(Date)
    knowledge_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    algorithm_version: Mapped[str] = mapped_column(String(40))
    input_bar_version_hash: Mapped[str] = mapped_column(String(64))
    action_version_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))


@final
class AdjustmentDatasetActionRow(Base):
    __tablename__: str = "adjustment_dataset_action"
    __table_args__: tuple[dict[str, str]] = ({"schema": "market"},)

    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.adjustment_dataset.id", ondelete="CASCADE"),
        primary_key=True,
    )
    corporate_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.corporate_action.id"),
        primary_key=True,
    )
    action_key: Mapped[UUID] = mapped_column()
    action_version: Mapped[int] = mapped_column(Integer)
    event_date: Mapped[date] = mapped_column(Date)
    event_price_factor: Mapped[Decimal] = mapped_column(Numeric(32, 16))
    event_volume_factor: Mapped[Decimal] = mapped_column(Numeric(32, 16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )


@final
class AdjustedMarketBarRow(Base):
    __tablename__: str = "adjusted_market_bar"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("dataset_id", "trading_date", name="uq_adjusted_market_bar_date"),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.adjustment_dataset.id", ondelete="CASCADE"),
        index=True,
    )
    source_bar_id: Mapped[UUID] = mapped_column(ForeignKey("market.market_bar.id"))
    trading_date: Mapped[date] = mapped_column(Date)
    open_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    low_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    close_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    volume: Mapped[int] = mapped_column(BigInteger)
    trading_value: Mapped[Decimal] = mapped_column(Numeric(32, 8))
    price_factor: Mapped[Decimal] = mapped_column(Numeric(32, 16))
    volume_factor: Mapped[Decimal] = mapped_column(Numeric(32, 16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )
