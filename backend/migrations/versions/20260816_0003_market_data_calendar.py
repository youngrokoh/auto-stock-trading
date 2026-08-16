import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0003"
down_revision: str | None = "20260814_0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "market_calendar",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("exchange", sa.String(12), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("session_type", sa.String(16), nullable=False),
        sa.Column("session_status", sa.String(16), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True)),
        sa.Column("closes_at", sa.DateTime(timezone=True)),
        sa.Column("exchange_timezone", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(240)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_reference", sa.String(240), nullable=False),
        sa.Column("source_as_of", sa.Date(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_state", sa.String(16), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("raw_response_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "session_status IN ('open', 'closed', 'shortened')",
            name="ck_market_calendar_session_status",
        ),
        sa.CheckConstraint(
            "verification_state IN ('pending', 'confirmed', 'conflict')",
            name="ck_market_calendar_verification_state",
        ),
        sa.CheckConstraint(
            """
            (session_status = 'closed' AND opens_at IS NULL AND closes_at IS NULL) OR
            (session_status IN ('open', 'shortened') AND opens_at IS NOT NULL
             AND closes_at IS NOT NULL AND opens_at < closes_at)
            """,
            name="ck_market_calendar_session_window",
        ),
        sa.CheckConstraint(
            """
            (verification_state = 'confirmed' AND confirmed_at IS NOT NULL) OR
            (verification_state IN ('pending', 'conflict') AND confirmed_at IS NULL)
            """,
            name="ck_market_calendar_confirmation",
        ),
        sa.CheckConstraint("version >= 1", name="ck_market_calendar_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_market_calendar_validity",
        ),
        sa.ForeignKeyConstraint(
            ["raw_response_id"],
            ["operations.raw_api_response.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "country",
            "exchange",
            "trading_date",
            "session_type",
            "version",
            name="uq_market_calendar_version",
        ),
        schema="reference",
    )
    op.create_index(
        "ix_market_calendar_exchange_date",
        "market_calendar",
        ["exchange", "trading_date"],
        schema="reference",
    )
    op.create_index(
        "uq_market_calendar_current",
        "market_calendar",
        ["country", "exchange", "trading_date", "session_type"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("market_calendar", schema="reference")
