"""ETF 분류 사실 행(ADR-0021). `market_data_rows`가 이미 커서 별 모듈로 둔다."""

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
class EtfIndexClassificationRow(Base):
    """추종 지수의 버전 사실. 위험 판정의 입력은 덮어써지는 스냅샷이 아니라 이 행이다.

    같은 값 재관측은 증거(as_of·received_at·raw)만 갱신하고, 값이 바뀌면 이전 버전을 보존한
    새 버전이 된다 — 그래야 "왜 그 주문이 통과했는가"를 나중에 재구성할 수 있다.
    """

    __tablename__: str = "etf_index_classification"
    __table_args__: tuple[UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint(
            "symbol",
            "source",
            "version",
            name="uq_etf_index_classification_version",
        ),
        Index(
            "uq_etf_index_classification_current",
            "symbol",
            "source",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        {"schema": "reference"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(9))
    index_name: Mapped[str] = mapped_column(String(120))
    tracking_multiple: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    source: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[UUID] = mapped_column(
        ForeignKey("operations.raw_api_response.id"),
    )
