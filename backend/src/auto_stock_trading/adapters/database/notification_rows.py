"""알림 아웃박스 테이블 매핑(리비전 `20260824_0028`)."""

from datetime import datetime  # noqa: TC003 — SQLAlchemy가 실행 시점에 주석을 해석한다
from typing import final
from uuid import UUID  # noqa: TC003 — 같은 이유

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class NotificationOutboxRow(Base):
    __tablename__: str = "notification_outbox"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint(
            "environment",
            "source",
            "source_id",
            name="uq_notification_outbox_event",
        ),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8), index=True)
    source: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    severity: Mapped[str] = mapped_column(String(8))
    body: Mapped[str] = mapped_column(String(4000))
    state: Mapped[str] = mapped_column(String(8))
    attempts: Mapped[int] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(500))
    event_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@final
class NotificationWatermarkRow(Base):
    __tablename__: str = "notification_watermark"
    __table_args__: tuple[UniqueConstraint, dict[str, str]] = (
        UniqueConstraint("environment", name="uq_notification_watermark_environment"),
        {"schema": "trading"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    environment: Mapped[str] = mapped_column(String(8))
    projected_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
