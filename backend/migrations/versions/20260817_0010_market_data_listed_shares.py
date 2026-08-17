import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0010"
down_revision: str | None = "20260817_0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "listed_share_count",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("share_count", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "raw_response_id",
            sa.Uuid(),
            sa.ForeignKey("operations.raw_api_response.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "source",
            "version",
            name="uq_listed_share_count_version",
        ),
        sa.CheckConstraint("share_count > 0", name="ck_listed_share_count_positive"),
        sa.CheckConstraint("version >= 1", name="ck_listed_share_count_version"),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at > valid_from",
            name="ck_listed_share_count_validity",
        ),
        schema="reference",
    )
    op.create_index(
        "uq_listed_share_count_current",
        "listed_share_count",
        ["instrument_id", "source"],
        unique=True,
        schema="reference",
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_listed_share_count_instrument_id",
        "listed_share_count",
        ["instrument_id"],
        schema="reference",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_listed_share_count_instrument_id",
        table_name="listed_share_count",
        schema="reference",
    )
    op.drop_index(
        "uq_listed_share_count_current",
        table_name="listed_share_count",
        schema="reference",
    )
    op.drop_table("listed_share_count", schema="reference")
