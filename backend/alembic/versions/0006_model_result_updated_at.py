"""model_results.updated_at（T6.5：janitor 依此判定卡死任务）。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_model_result_updated_at"
down_revision: str | None = "0005_refresh_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_results",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_results", "updated_at")
