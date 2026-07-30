"""数据集 schema（契约同源：docs/14 §3 DatasetAccepted/DatasetDetail/QualityReport）。"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class DatasetAccepted(BaseModel):
    dataset_id: uuid.UUID
    status: Literal["VALIDATING"] = "VALIDATING"


class DatasetDetail(BaseModel):
    id: uuid.UUID
    name: str
    status: Literal["UPLOADED", "VALIDATING", "VALIDATED", "FAILED", "ARCHIVED"]
    encoding: str | None = None
    preview: dict[str, Any] | None = None
    column_profile: list[dict[str, Any]] | None = None


class Issue(BaseModel):
    rule_id: str
    severity: Literal["blocker", "warning", "info"]
    column: str | None = None
    message: str
    detail: str | None = None
    suggestion: str = ""
    affected_rows: int | None = None


class QualityReport(BaseModel):
    status: Literal["PASSED", "PASSED_WITH_WARNINGS", "FAILED"]
    blockers: int
    warnings: int
    issues: list[Issue]
    column_profiles: list[dict[str, Any]]


class DatasetPage(BaseModel):
    items: list[DatasetDetail]
    next_cursor: str | None = None


class QuickFixAction(BaseModel):
    type: Literal["drop_column", "drop_duplicates", "to_missing", "remap_semantic"]
    column: str | None = None
    params: dict[str, Any] = {}


class QuickFixRequest(BaseModel):
    actions: list[QuickFixAction] = Field(min_length=1)


class DatasetVersion(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version_no: int
    transform_log: list[dict[str, Any]]
    created_at: Any  # datetime，由 ORM 序列化
