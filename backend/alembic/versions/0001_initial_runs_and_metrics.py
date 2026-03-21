"""initial runs and metrics tables

Revision ID: 0001
Revises:
Create Date: 2026-03-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type explicitly before the table that uses it.
    # Alembic autogenerate does this automatically; hand-written migrations
    # must do it manually or the CREATE TABLE will fail.
    run_status = postgresql.ENUM(
        "pending", "running", "done", "failed",
        name="run_status",
        create_type=False,  # we call create() ourselves below
    )
    run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_url", sa.String(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("num_requests", sa.Integer(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="run_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        # ARRAY(FLOAT) is Postgres-specific; fine here since asyncpg is our
        # only driver (see CLAUDE.md — no adapter swap for this table).
        sa.Column("latencies", postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column("p50", sa.Float(), nullable=False),
        sa.Column("p95", sa.Float(), nullable=False),
        sa.Column("p99", sa.Float(), nullable=False),
        sa.Column("throughput", sa.Float(), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Index run_id so fetching metrics for a run is fast even at scale.
    op.create_index("ix_metrics_run_id", "metrics", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_metrics_run_id", table_name="metrics")
    op.drop_table("metrics")
    op.drop_table("runs")
    # Drop the enum type after the table that owns it is gone.
    op.execute("DROP TYPE IF EXISTS run_status")
