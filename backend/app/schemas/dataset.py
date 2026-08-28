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
    # T6.1(docs/14 §5 变更记录 2026-08-28):受影响行号(0 基,≤20)与富文案修复指引
    row_indices: list[int] | None = None
    guidance: str | None = None


class QualityReport(BaseModel):
    status: Literal["PASSED", "PASSED_WITH_WARNINGS", "FAILED"]
    blockers: int
    warnings: int
    issues: list[Issue]
    column_profiles: list[dict[str, Any]]


class DatasetPage(BaseModel):
    items: list[DatasetDetail]
    next_cursor: str | None = None


class ResearchHints(BaseModel):
    """研究画像用户提示(POST /datasets/{id}/research-profile 请求体,全部可选)。"""

    research_type: str | None = None  # 期望的研究设计(cohort/time_series/...)
    time_column: str | None = None  # 随访/时间列名
    event_column: str | None = None  # 事件(结局)列名
    group_column: str | None = None  # 分组列名
    outcome: str | None = None  # 结局变量列名


class ResearchProfile(BaseModel):
    """研究画像结果(engines/research_profiler.detect_research_direction 输出契约)。"""

    research_type: str
    recommended_models: list[str]
    recommended_journals: list[str]
    confidence: float
    reasoning: str


class QuickFixAction(BaseModel):
    type: Literal[
        "drop_column",
        "drop_duplicates",
        "to_missing",
        "remap_semantic",
        # T6.8 扩展(docs/14 §5 变更记录 2026-08-28)
        "rename_column",
        "pivot_long_to_wide",
        "winsorize_outliers",
        "impute_missing",
        "drop_rows_with_pattern",
        "normalize_units",
    ]
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
