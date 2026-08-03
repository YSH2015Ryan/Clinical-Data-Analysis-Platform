"""preparation_jobs 表 + datasets.source_type 放开 'prepared'（docs/13；docs/05 §8）

Revision ID: 0004_preparation_jobs
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_preparation_jobs"
down_revision: str | None = "0003_report_template_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preparation_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lab_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id"),
            nullable=False,
        ),
        sa.Column(
            "diag_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id"),
            nullable=False,
        ),
        sa.Column("decisions", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column(
            "result_dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id"),
            nullable=True,
        ),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED')",
            name="ck_preparation_jobs_status",
        ),
    )
    op.drop_constraint("ck_datasets_source_type", "datasets", type_="check")
    op.create_check_constraint(
        "ck_datasets_source_type",
        "datasets",
        "source_type IN ('csv','excel','fhir','omop','prepared')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_datasets_source_type", "datasets", type_="check")
    op.create_check_constraint(
        "ck_datasets_source_type", "datasets", "source_type IN ('csv','excel','fhir','omop')"
    )
    op.drop_table("preparation_jobs")
