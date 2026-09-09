"""Align database checks with the current GitHub application contract.

The mainline ORM accepts time-series runs and prepared datasets, while the
original initial migration predates those values. This forward migration is
idempotent for databases that already received the checks from the local
analysis branch.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mainline_contract_alignment"
down_revision: str | None = "0008_dataset_insights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ensure_check_constraint(
    table: str,
    column: str,
    required_value: str,
    constraint_name: str,
    expression: str,
) -> None:
    connection = op.get_bind()
    constraints = connection.execute(
        sa.text(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = CAST(:table_name AS regclass)
              AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE :column_pattern
            """
        ),
        {"table_name": table, "column_pattern": f"%{column}%"},
    ).all()
    if any(required_value in str(definition) for _, definition in constraints):
        return
    for existing_name, _ in constraints:
        connection.exec_driver_sql(
            f'ALTER TABLE "{table}" DROP CONSTRAINT "{existing_name}"'
        )
    connection.exec_driver_sql(
        f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" CHECK ({expression})'
    )


def upgrade() -> None:
    _ensure_check_constraint(
        "analysis_runs",
        "task_type",
        "time_series",
        "ck_analysis_runs_task_type",
        "task_type IN ('survival','classification','regression','time_series')",
    )
    _ensure_check_constraint(
        "datasets",
        "source_type",
        "prepared",
        "ck_datasets_source_type",
        "source_type IN ('csv','excel','fhir','omop','prepared')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        'ALTER TABLE "analysis_runs" DROP CONSTRAINT IF EXISTS "ck_analysis_runs_task_type"'
    )
    connection.exec_driver_sql(
        'ALTER TABLE "analysis_runs" DROP CONSTRAINT IF EXISTS "ck_analysis_runs_ck_analysis_runs_task_type"'
    )
    connection.exec_driver_sql(
        'ALTER TABLE "analysis_runs" ADD CONSTRAINT "ck_analysis_runs_task_type" '
        "CHECK (task_type IN ('survival','classification','regression'))"
    )
    connection.exec_driver_sql(
        'ALTER TABLE "datasets" DROP CONSTRAINT IF EXISTS "ck_datasets_source_type"'
    )
    connection.exec_driver_sql(
        'ALTER TABLE "datasets" DROP CONSTRAINT IF EXISTS "ck_datasets_ck_datasets_source_type"'
    )
    connection.exec_driver_sql(
        'ALTER TABLE "datasets" ADD CONSTRAINT "ck_datasets_source_type" '
        "CHECK (source_type IN ('csv','excel','fhir','omop'))"
    )
