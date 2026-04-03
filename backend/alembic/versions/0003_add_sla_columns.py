"""add sla_config and sla_result to runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable JSON: NULL means no SLA thresholds were configured for that run.
    op.add_column("runs", sa.Column("sla_config", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("sla_result", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "sla_result")
    op.drop_column("runs", "sla_config")
