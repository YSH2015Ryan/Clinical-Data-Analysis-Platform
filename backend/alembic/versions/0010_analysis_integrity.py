"""Add deterministic analysis integrity findings to analysis runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_analysis_integrity"
down_revision: str | None = "0009_mainline_contract_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("integrity", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_runs", "integrity")
