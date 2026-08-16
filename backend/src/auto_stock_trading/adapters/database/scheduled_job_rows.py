from datetime import datetime
from typing import final
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from auto_stock_trading.adapters.database.market_data_rows import Base


@final
class ScheduledJobRunRow(Base):
    __tablename__: str = "scheduled_job_run"
    __table_args__: tuple[UniqueConstraint, Index, dict[str, str]] = (
        UniqueConstraint(
            "task_name",
            "execution_key",
            name="uq_scheduled_job_execution",
        ),
        Index("ix_scheduled_job_state_lease", "state", "lease_expires_at"),
        {"schema": "operations"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_name: Mapped[str] = mapped_column(String(80))
    execution_key: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(16))
    owner_token: Mapped[UUID] = mapped_column()
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
