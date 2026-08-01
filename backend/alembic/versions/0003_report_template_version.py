"""reports 补 template_version 列（docs/13；docs/10 §3 模板版本化）

Revision ID: 0003_report_template_version
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_report_template_version"
down_revision: str | None = "0002_analysis_run_model_params"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("template_version", sa.Text(), nullable=False, server_default="1.0.0"),
    )


def downgrade() -> None:
    op.drop_column("reports", "template_version")
