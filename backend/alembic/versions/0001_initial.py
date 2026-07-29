"""initial schema —— 对应 docs/13-Database-Design.md 全部 12 表

Revision ID: 0001_initial
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("email", postgresql.CITEXT, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("role IN ('admin','researcher','viewer')", name="ck_users_role"),
    )

    op.create_table(
        "projects",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("owner_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_projects_owner_active", "projects", ["owner_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "datasets",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text, nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("encoding", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="UPLOADED"),
        sa.Column("column_profile", postgresql.JSONB, nullable=True),
        sa.Column("preview", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('csv','excel','fhir','omop')", name="ck_datasets_source_type"
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADED','VALIDATING','VALIDATED','FAILED','ARCHIVED')",
            name="ck_datasets_status",
        ),
    )
    op.create_index(
        "ix_datasets_project_created", "datasets", ["project_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "dataset_id", UUID, sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
        sa.Column("transform_log", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint(
            "dataset_id", "version_no", name="uq_dataset_versions_dataset_id_version_no"
        ),
    )

    op.create_table(
        "quality_reports",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "dataset_id", UUID, sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "dataset_version_id", UUID,
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("blockers", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warnings", sa.Integer, nullable=False, server_default="0"),
        sa.Column("issues", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("column_profiles", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('PASSED','PASSED_WITH_WARNINGS','FAILED')",
            name="ck_quality_reports_status",
        ),
    )
    op.create_index(
        "ix_quality_reports_version_created", "quality_reports",
        ["dataset_version_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "dataset_version_id", UUID,
            sa.ForeignKey("dataset_versions.id"), nullable=False,
        ),
        sa.Column("task_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("preprocess_config", postgresql.JSONB, nullable=False),
        sa.Column("selected_models", postgresql.JSONB, nullable=False),
        sa.Column("task_detection", postgresql.JSONB, nullable=True),
        sa.Column("celery_chain_id", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "task_type IN ('survival','classification','regression')",
            name="ck_analysis_runs_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PREPROCESSING','MODELING','COMPARING',"
            "'COMPLETED','FAILED','CANCELED')",
            name="ck_analysis_runs_status",
        ),
    )
    op.create_index(
        "ix_analysis_runs_project_created", "analysis_runs",
        ["project_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])

    op.create_table(
        "preprocess_snapshots",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("steps", postgresql.JSONB, nullable=False),
        sa.Column("feature_matrix_uri", sa.Text, nullable=False),
        sa.Column("input_hash", sa.Text, nullable=False),
    )

    op.create_table(
        "model_plugins",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Text, nullable=False),
        sa.Column("task_types", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("capability", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("default_params", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("entry_point", sa.Text, nullable=False),
    )

    op.create_table(
        "model_results",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("model_key", sa.Text, sa.ForeignKey("model_plugins.key"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("metrics", postgresql.JSONB, nullable=True),
        sa.Column("artifacts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("explainability", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')",
            name="ck_model_results_status",
        ),
        sa.UniqueConstraint("run_id", "model_key"),
    )
    op.create_index("ix_model_results_run", "model_results", ["run_id"])

    op.create_table(
        "comparisons",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("ranking", postgresql.JSONB, nullable=False),
        sa.Column("recommendation", postgresql.JSONB, nullable=False),
        sa.Column("comparison_charts", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "reports",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("format", sa.Text, nullable=False),
        sa.Column("template_key", sa.Text, nullable=False, server_default="clinical_report_zh"),
        sa.Column("storage_uri", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("format IN ('pdf','html','markdown','docx')", name="ck_reports_format"),
        sa.CheckConstraint("status IN ('PENDING','READY','FAILED')", name="ck_reports_status"),
    )
    op.create_index(
        "ix_reports_run_created", "reports", ["run_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=True),
        sa.Column("resource_id", UUID, nullable=True),
        sa.Column("detail", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index(
        "ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"]
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("reports")
    op.drop_table("comparisons")
    op.drop_table("model_results")
    op.drop_table("model_plugins")
    op.drop_table("preprocess_snapshots")
    op.drop_table("analysis_runs")
    op.drop_table("quality_reports")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
    op.drop_table("projects")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS citext")
