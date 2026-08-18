import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0014"
down_revision: str | None = "20260818_0013"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ENVIRONMENTS = "('paper', 'live')"
_ORDER_STATES = "('planned', 'submitted', 'partially_filled', 'filled', 'rejected', 'canceled')"
_AUTOMATION_STATES = "('disabled', 'armed', 'running', 'paused', 'emergency_stop')"
_PLANNED_FIELDS = (
    "state <> 'planned' OR (quantity > 0 AND limit_price > 0 AND reference_price > 0"
    " AND reference_source IS NOT NULL AND reference_received_at IS NOT NULL)"
)


def upgrade() -> None:
    _ = op.create_table(
        "account_snapshot",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("account_reference", sa.String(12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cash_balance", sa.Numeric(24, 0), nullable=False),
        sa.Column("orderable_cash", sa.Numeric(24, 0), nullable=False),
        sa.Column("position_value", sa.Numeric(24, 0), nullable=False),
        sa.Column("nav", sa.Numeric(24, 0), nullable=False),
        sa.Column("broker_net_asset", sa.Numeric(24, 0), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "raw_response_id",
            sa.Uuid(),
            sa.ForeignKey("operations.raw_api_response.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"environment IN {_ENVIRONMENTS}",
            name="ck_account_snapshot_environment",
        ),
        sa.CheckConstraint(
            "cash_balance >= 0 AND orderable_cash >= 0 AND position_value >= 0 AND nav >= 0",
            name="ck_account_snapshot_amounts",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_account_snapshot_session",
        "account_snapshot",
        ["environment", "trading_date", "received_at"],
        schema="trading",
    )

    _ = op.create_table(
        "account_position",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("trading.account_snapshot.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("orderable_quantity", sa.Integer(), nullable=False),
        sa.Column("average_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("current_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("evaluation_amount", sa.Numeric(24, 0), nullable=False),
        sa.Column("profit_loss", sa.Numeric(24, 0), nullable=False),
        sa.UniqueConstraint(
            "snapshot_id",
            "instrument_id",
            name="uq_account_position_snapshot",
        ),
        sa.CheckConstraint(
            "quantity >= 0 AND orderable_quantity >= 0 AND orderable_quantity <= quantity",
            name="ck_account_position_quantity",
        ),
        schema="trading",
    )

    _ = op.create_table(
        "automation_state",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(40)),
        sa.Column("trading_date", sa.Date()),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("environment", name="uq_automation_state_environment"),
        sa.CheckConstraint(
            f"state IN {_AUTOMATION_STATES}",
            name="ck_automation_state_state",
        ),
        sa.CheckConstraint(
            f"environment IN {_ENVIRONMENTS}",
            name="ck_automation_state_environment",
        ),
        schema="trading",
    )

    _ = op.create_table(
        "automation_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("previous_state", sa.String(16)),
        sa.Column("state", sa.String(16)),
        sa.Column("reason_code", sa.String(40)),
        sa.Column("detail", sa.String(500)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('state_change', 'api_failure')",
            name="ck_automation_event_type",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_automation_event_window",
        "automation_event",
        ["environment", "event_type", "occurred_at"],
        schema="trading",
    )

    _ = op.create_table(
        "order_plan",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("environment", sa.String(8), nullable=False),
        sa.Column("strategy_name", sa.String(40), nullable=False),
        sa.Column("strategy_version", sa.String(16), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column(
            "account_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("trading.account_snapshot.id", ondelete="SET NULL"),
        ),
        sa.Column("nav_basis", sa.Numeric(24, 0)),
        sa.Column("session_open_nav", sa.Numeric(24, 0)),
        sa.Column("automation_state", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("block_code", sa.String(40)),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('created', 'blocked')",
            name="ck_order_plan_status",
        ),
        sa.CheckConstraint(
            "status <> 'blocked' OR block_code IS NOT NULL",
            name="ck_order_plan_block_code",
        ),
        sa.CheckConstraint(
            f"environment IN {_ENVIRONMENTS}",
            name="ck_order_plan_environment",
        ),
        schema="trading",
    )
    op.create_index(
        "ix_order_plan_lookup",
        "order_plan",
        ["environment", "planned_at"],
        schema="trading",
    )

    _ = op.create_table(
        "order",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("trading.order_plan.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_order_id", sa.String(32), nullable=False),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("reference.instrument.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("order_type", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(24, 8)),
        sa.Column("reference_price", sa.Numeric(24, 8)),
        sa.Column("reference_source", sa.String(32)),
        sa.Column("reference_received_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("reject_code", sa.String(40)),
        sa.Column("broker_order_id", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_order_id", name="uq_order_client_order_id"),
        sa.UniqueConstraint("plan_id", "sequence", name="uq_order_plan_sequence"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_order_side"),
        sa.CheckConstraint("order_type IN ('limit')", name="ck_order_type"),
        sa.CheckConstraint(f"state IN {_ORDER_STATES}", name="ck_order_state"),
        sa.CheckConstraint(
            "quantity >= 0 AND filled_quantity >= 0 AND filled_quantity <= quantity",
            name="ck_order_quantity",
        ),
        sa.CheckConstraint(_PLANNED_FIELDS, name="ck_order_planned_fields"),
        sa.CheckConstraint(
            "state <> 'rejected' OR reject_code IS NOT NULL",
            name="ck_order_reject_code",
        ),
        sa.CheckConstraint(
            "limit_price IS NULL OR limit_price > 0",
            name="ck_order_limit_price",
        ),
        schema="trading",
    )

    _ = op.create_table(
        "order_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("trading.order.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.String(20)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(40)),
        sa.Column("detail", sa.String(500)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "sequence", name="uq_order_event_sequence"),
        sa.CheckConstraint(f"state IN {_ORDER_STATES}", name="ck_order_event_state"),
        schema="trading",
    )

    _ = op.create_table(
        "risk_decision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("trading.order.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_code", sa.String(40), nullable=False),
        sa.Column("limit_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("projected_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("order_id", "rule_code", name="uq_risk_decision_rule"),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_table("risk_decision", schema="trading")
    op.drop_table("order_event", schema="trading")
    op.drop_table("order", schema="trading")
    op.drop_index("ix_order_plan_lookup", table_name="order_plan", schema="trading")
    op.drop_table("order_plan", schema="trading")
    op.drop_index("ix_automation_event_window", table_name="automation_event", schema="trading")
    op.drop_table("automation_event", schema="trading")
    op.drop_table("automation_state", schema="trading")
    op.drop_table("account_position", schema="trading")
    op.drop_index("ix_account_snapshot_session", table_name="account_snapshot", schema="trading")
    op.drop_table("account_snapshot", schema="trading")
