from datetime import datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from sqlalchemy import (
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
class FinancialReportRow(Base):
    __tablename__: str = "financial_report"
    __table_args__: tuple[UniqueConstraint, UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint(
            "instrument_id",
            "bsns_year",
            "reprt_code",
            "fs_div",
            "version",
            name="uq_financial_report_version",
        ),
        UniqueConstraint(
            "instrument_id",
            "bsns_year",
            "reprt_code",
            "fs_div",
            "rcept_no",
            name="uq_financial_report_receipt",
        ),
        Index(
            "uq_financial_report_current",
            "instrument_id",
            "bsns_year",
            "reprt_code",
            "fs_div",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        {"schema": "fundamental"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.instrument.id", ondelete="CASCADE"),
    )
    corp_code: Mapped[str] = mapped_column(String(8))
    bsns_year: Mapped[int] = mapped_column(Integer)
    reprt_code: Mapped[str] = mapped_column(String(5))
    fs_div: Mapped[str] = mapped_column(String(3))
    rcept_no: Mapped[str] = mapped_column(String(14))
    currency: Mapped[str] = mapped_column(String(3))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.raw_api_response.id"),
    )


@final
class FinancialStatementLineRow(Base):
    __tablename__: str = "financial_statement_line"
    __table_args__: tuple[UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint("report_id", "line_seq", name="uq_financial_statement_line_seq"),
        Index("ix_financial_statement_line_report", "report_id"),
        {"schema": "fundamental"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID] = mapped_column(ForeignKey("fundamental.financial_report.id"))
    line_seq: Mapped[int] = mapped_column(Integer)
    sj_div: Mapped[str] = mapped_column(String(3))
    account_id: Mapped[str | None] = mapped_column(String(255))
    account_nm: Mapped[str] = mapped_column(String(200))
    account_detail: Mapped[str | None] = mapped_column(String(200))
    ord: Mapped[int] = mapped_column(Integer)
    thstrm_nm: Mapped[str] = mapped_column(String(40))
    thstrm_amount: Mapped[Decimal | None] = mapped_column(Numeric(32, 4))
    frmtrm_nm: Mapped[str | None] = mapped_column(String(40))
    frmtrm_amount: Mapped[Decimal | None] = mapped_column(Numeric(32, 4))
    bfefrmtrm_nm: Mapped[str | None] = mapped_column(String(40))
    bfefrmtrm_amount: Mapped[Decimal | None] = mapped_column(Numeric(32, 4))
