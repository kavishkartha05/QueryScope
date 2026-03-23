"""initial runs and metrics tables

Revision ID: 0001
Revises:
Create Date: 2026-03-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_url", sa.String(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("num_requests", sa.Integer(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="run_status", create_type=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        # sa.JSON works on both PostgreSQL and MySQL (cross-DB adapter swap demo).
        sa.Column("latencies", sa.JSON(), nullable=False),
        sa.Column("p50", sa.Float(), nullable=False),
        sa.Column("p95", sa.Float(), nullable=False),
        sa.Column("p99", sa.Float(), nullable=False),
        sa.Column("throughput", sa.Float(), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metrics_run_id", "metrics", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_metrics_run_id", table_name="metrics")
    op.drop_table("metrics")
    op.drop_table("runs")
    op.execute("DROP TYPE IF EXISTS run_status")
    