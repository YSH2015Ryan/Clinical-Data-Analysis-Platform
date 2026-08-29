"""admin_settings 运行层配置表（T6.6：LLM 设置界面，敏感值 Fernet 密文存储）。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_admin_settings"
down_revision: str | None = "0006_model_result_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("admin_settings")
