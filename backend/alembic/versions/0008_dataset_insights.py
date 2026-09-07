"""dataset_insights 数据体表（P2-2，docs/08 §3.2 阶段 A：上传后自动产出的数据体检）。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_dataset_insights"
down_revision: str | None = "0007_admin_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_insights",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column(
            "dataset_id",
            sa.UUID(),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.UUID(),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # EDA 引擎产出（分布/缺失/相关性/样本量）+ 任务推荐 + 研究画像 + 自动修复日志
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_dataset_insights_dataset", "dataset_insights", ["dataset_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_insights_dataset", table_name="dataset_insights")
    op.drop_table("dataset_insights")
