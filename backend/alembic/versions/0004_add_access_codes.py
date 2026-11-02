"""add access_codes table and runs.access_code_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_codes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, unique=True),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_access_codes_code_hash", "access_codes", ["code_hash"])

    # NULL access_code_id means "shared demo owner": readable by every code,
    # modifiable only by an admin. Pre-existing runs therefore become demo runs.
    # No ondelete action: codes are revoked, never deleted, so a run can never
    # silently flip into the demo scope.
    op.add_column(
        "runs",
        sa.Column(
            "access_code_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("access_codes.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_runs_access_code_id", "runs", ["access_code_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_access_code_id", table_name="runs")
    op.drop_column("runs", "access_code_id")
    op.drop_index("ix_access_codes_code_hash", table_name="access_codes")
    op.drop_table("access_codes")
