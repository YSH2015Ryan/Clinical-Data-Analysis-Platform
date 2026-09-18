"""Add exploratory_mode flag to analysis runs (updateplan §72 Exploratory Mode)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_exploratory_mode"
down_revision: str | None = "0010_analysis_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "exploratory_mode", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "exploratory_mode")
