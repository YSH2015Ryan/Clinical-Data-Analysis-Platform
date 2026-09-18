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
    # P0-04（updateplan §15）：severity 升四级，新增 critical（须人工复核但不阻断）
    severity: Literal["blocker", "critical", "warning", "info"]
    column: str | None = None
    message: str
    detail: str | None = None
    suggestion: str = ""
    affected_rows: int | None = None
    # T6.1(docs/14 §5 变更记录 2026-08-28):受影响行号(0 基,≤20)与富文案修复指引
    row_indices: list[int] | None = None
    guidance: str | None = None
    # T6.7(docs/14 §5 变更记录 2026-08-27):LLM 人话版解释；功能关闭或生成失败时缺省
    llm_explanation: str | None = None
    # P2-3(docs/14 §5 变更记录 2026-09-07):结构化修复指引（问题→影响→修法，修法含一键动作契约）
    fix_guidance: dict[str, Any] | None = None


class QualityReport(BaseModel):
    status: Literal["PASSED", "PASSED_WITH_WARNINGS", "FAILED"]
    blockers: int
    warnings: int
    # P0-04（updateplan §15）：CRITICAL 档计数，缺省 0 兼容旧报告
    criticals: int = 0
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


class ResearchQuestion(BaseModel):
    """LLM 生成的研究问题建议（T6.7；模型/图表均来自引擎白名单）。"""

    question: str
    design: str
    models: list[str]
    charts: list[str]


class ResearchProfile(BaseModel):
    """研究画像结果(engines/research_profiler.detect_research_direction 输出契约)。"""

    research_type: str
    recommended_models: list[str]
    recommended_journals: list[str]
    confidence: float
    reasoning: str
    # T6.7(docs/14 §5 变更记录 2026-08-27):LLM 增强研究问题；功能关闭或 LLM 不可用时为 None
    research_questions: list[ResearchQuestion] | None = None


class SampleSizeAdvice(BaseModel):
    """样本量/功效经验规则核对（T6.9；数值全部来自数据集真实统计）。"""

    rule: str
    value: float | None = None  # 无法计算时（缺事件计数等）为 None
    threshold: float
    meets: bool
    text: str


class ResearchTemplateSuggestion(BaseModel):
    """科研流程模板建议（T6.9，docs/14 §5 变更记录 2026-08-27）。"""

    key: Literal["prognostic_model", "risk_factor", "dose_response", "longitudinal"]
    name: str
    description: str
    applicable: bool
    reasons: list[str]
    task_type: Literal["survival", "classification", "regression"]
    models: list[str]
    charts: list[str]
    sample_size: list[SampleSizeAdvice]


class ResearchTemplatesResponse(BaseModel):
    templates: list[ResearchTemplateSuggestion]


class UnivariateScreenRequest(BaseModel):
    """单因素筛选请求（T6.10，docs/14 §5 变更记录 2026-08-27）。"""

    task_type: Literal["survival", "classification", "regression"]
    label_col: str | None = None
    time_col: str | None = None
    event_col: str | None = None
    features: list[str] | None = None  # 空 → 自动取除结局外全部列（上限 50）
    alpha: float = 0.05
    # P1-13（§30）：多重比较校正方法，默认 BH(FDR)；none 时响应附 correction_warning
    correction: Literal["bh", "bonferroni", "none"] = "bh"


class UnivariateScreenRow(BaseModel):
    feature: str
    test: str
    statistic: float | None = None
    effect: float | None = None
    p_value: float
    p_adjusted: float | None = None  # P1-13：校正后 p 值（§30 raw/adjusted 并列）
    n_used: int
    selected: bool  # 基于校正后 p 值判定


class UnivariateScreenResult(BaseModel):
    task_type: str
    alpha: float
    rows: list[UnivariateScreenRow]
    selected_features: list[str]
    correction: str = "bh"
    correction_label: str = "Benjamini–Hochberg(FDR)"
    n_tests: int = 0
    correction_warning: str | None = None  # correction=none 时固定警告文案


class SubgroupAnalysisRequest(BaseModel):
    """亚组分析请求（T6.10）。"""

    task_type: Literal["survival", "classification", "regression"]
    exposure: str
    subgroup_vars: list[str] = Field(min_length=1)
    label_col: str | None = None
    time_col: str | None = None
    event_col: str | None = None
    # P1-13（§30）：跨亚组变量的交互检验批量校正
    correction: Literal["bh", "bonferroni", "none"] = "bh"


class SubgroupLevelEffect(BaseModel):
    level: str
    n: int
    effect: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    note: str | None = None


class SubgroupResult(BaseModel):
    variable: str
    levels: list[SubgroupLevelEffect]
    interaction_p: float | None = None
    interaction_p_adjusted: float | None = None  # P1-13：校正后交互 p


class SubgroupAnalysisResult(BaseModel):
    task_type: str
    exposure: str
    subgroups: list[SubgroupResult]
    correction: str = "bh"
    correction_label: str = "Benjamini–Hochberg(FDR)"
    n_tests: int = 0
    correction_warning: str | None = None


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


class DatasetInsightOut(BaseModel):
    """数据体检（P2-2，docs/14 §5 变更记录 2026-09-07）：阶段 A 自动产出。

    payload = {eda, task_recommendation, research_profile, auto_fix_log, summary}，
    全部数值来自引擎真实计算；结构与 docs/08 §3.2 一致。
    """

    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID
    created_at: Any  # datetime，由 ORM 序列化
    payload: dict[str, Any]


class AnalysisDraft(BaseModel):
    """分析草稿（P1-3，docs/14 §5 变更记录 2026-09-07）：单页确认所需全部默认值。

    识别失败时 task_type/task_detection 为 None、standard_models 为空，
    前端回退逐步向导。
    """

    task_type: Literal["survival", "classification", "regression"] | None
    task_detection: dict[str, Any] | None  # engines/task_detection.TaskDetection.to_dict()
    preprocess_config: dict[str, Any]
    standard_models: list[str]
