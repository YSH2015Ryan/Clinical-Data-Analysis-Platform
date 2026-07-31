"""analysis_runs 补 model_params 列（docs/13；docs/14 AnalysisRunCreate.model_params 落地）

Revision ID: 0002_analysis_run_model_params
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_analysis_run_model_params"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("model_params", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "model_params")
