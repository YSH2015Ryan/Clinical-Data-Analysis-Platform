"""数据集端点（冻结契约 docs/14 §3）。

上传：POST /projects/{id}/datasets → 202；
查询（T2.5）：GET /projects/{id}/datasets 列表、GET /datasets/{id} 详情、
GET /datasets/{id}/quality-report 最新质量报告。
"""

import uuid
from typing import Any

import pandas as pd
from anyio import to_thread
from fastapi import APIRouter, Depends, Form, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_registry, require_role
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.db import get_db
from app.engines import parser
from app.engines.model_tiers import tier_of
from app.engines.preprocessing import validate_dsl
from app.engines.quickfix import QuickFixAction
from app.engines.research_profiler import detect_research_direction
from app.engines.research_templates import evaluate_templates
from app.engines.screening import subgroup_analysis, univariate_screen
from app.engines.task_detection import detect_task_from_profile
from app.schemas.auth import CurrentUser
from app.schemas.dataset import (
    AnalysisDraft,
    DatasetAccepted,
    DatasetDetail,
    DatasetInsightOut,
    DatasetPage,
    DatasetVersion,
    QualityReport,
    QuickFixRequest,
    ResearchHints,
    ResearchProfile,
    ResearchTemplatesResponse,
    SubgroupAnalysisRequest,
    SubgroupAnalysisResult,
    UnivariateScreenRequest,
    UnivariateScreenResult,
)
from app.schemas.preparation import (
    PreparationApplyRequest,
    PreparationJob,
    PreparationPreview,
    PreparationPreviewRequest,
)
from app.services import audit as audit_service
from app.services import datasets as dataset_service
from app.services import llm_tasks
from app.services import plugins as plugin_service
from app.services import preparation as preparation_service
from app.services import projects as project_service
from app.services import quickfix as quickfix_service
from app.services import settings as settings_service
from app.services.llm import init_llm_service_from_runtime
from app.services.storage import key_from_uri, storage_from_settings
from app.workers.dataset_tasks import validate_dataset
from app.workers.insight_tasks import auto_dataset_insight
from app.workers.preparation_tasks import run_preparation

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])
dataset_router = APIRouter(prefix="/datasets", tags=["datasets"])
preparation_router = APIRouter(prefix="/preparations", tags=["datasets"])


@router.post("", status_code=202, response_model=DatasetAccepted)
async def upload_dataset(
    project_id: uuid.UUID,
    file: UploadFile,
    name: str | None = Form(default=None),
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> DatasetAccepted:
    project = await project_service.get_project(db, user, project_id)
    if project is None:
        raise not_found("project", str(project_id))
    if file.filename is None:
        raise AppError(code="VALIDATION_ERROR", status=400, message="缺少文件名")

    settings = get_settings()
    dataset = await dataset_service.ingest_upload(
        db,
        storage_from_settings(),
        project_id=project_id,
        filename=name or file.filename,
        stream=file.file,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        declared_size=file.size,
    )
    await audit_service.record(
        db,
        "dataset.upload",
        user_id=user.id,
        resource_type="dataset",
        resource_id=dataset.id,
        detail={"filename": file.filename, "size": dataset.file_size},
    )
    await db.commit()

    try:
        validate_dataset.delay(str(dataset.id))
    except Exception as exc:
        dataset.status = "FAILED"
        await db.commit()
        raise AppError("TASK_DISPATCH_FAILED", 503, "数据校验任务暂时无法排队，请稍后重试") from exc
    return DatasetAccepted(dataset_id=dataset.id)


@router.get("", response_model=DatasetPage)
async def list_datasets(
    project_id: uuid.UUID,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetPage:
    project = await project_service.get_project(db, user, project_id)
    if project is None:
        raise not_found("project", str(project_id))
    items, next_cursor = await dataset_service.list_datasets(db, user, project_id, cursor, limit)
    return DatasetPage(
        items=[DatasetDetail.model_validate(d, from_attributes=True) for d in items],
        next_cursor=next_cursor,
    )


@dataset_router.get("/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetDetail:
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    return DatasetDetail.model_validate(dataset, from_attributes=True)


@dataset_router.get("/{dataset_id}/quality-report", response_model=QualityReport)
async def get_quality_report(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityReport:
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    report = await dataset_service.get_latest_report(db, dataset_id)
    if report is None:
        raise not_found("report", str(dataset_id))
    return QualityReport.model_validate(report, from_attributes=True)


@dataset_router.get("/{dataset_id}/insight", response_model=DatasetInsightOut)
async def get_dataset_insight(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetInsightOut:
    """数据体检（P2-2，docs/14 §5 变更记录 2026-09-07）：阶段 A 自动产出，404 = 尚未生成。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    insight = await dataset_service.get_latest_insight(db, dataset_id)
    if insight is None:
        raise not_found("insight", str(dataset_id))
    return DatasetInsightOut.model_validate(insight, from_attributes=True)


@dataset_router.get("/{dataset_id}/analysis-draft", response_model=AnalysisDraft)
async def get_analysis_draft(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    registry: Any = Depends(get_registry),
) -> AnalysisDraft:
    """分析草稿（P1-3）：单页确认所需默认值 —— 推荐任务 + 预处理配置 + 标准套餐模型。

    识别失败不报错：task_type/standard_models 置空，前端回退逐步向导（人工兜底）。
    """
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    if not dataset.column_profile:
        raise AppError(
            code="DRAFT_UNAVAILABLE",
            status=400,
            message="数据集尚未完成校验，无法生成分析草稿",
        )
    det = detect_task_from_profile(dataset.column_profile)
    task_type = det.recommended_task
    config = await dataset_service.recommended_preprocess_dsl(
        db, dataset, storage_from_settings()
    )
    # 旧画像/推荐路径可能返回缺少 target 的 DSL；只用检测候选补齐空字段，
    # 不覆盖已有用户/推荐配置，也不把无成对随访+事件列的数据硬判为 survival。
    if task_type is not None:
        target = dict(config.get("target") or {})
        candidates = det.candidates

        def _top(kind: str) -> str | None:
            items = candidates.get(kind, [])
            return items[0].column if items else None

        if task_type == "survival":
            target["time_col"] = target.get("time_col") or _top("time_col")
            target["event_col"] = target.get("event_col") or _top("event_col")
        else:
            target["label_col"] = target.get("label_col") or _top("label_col")
        config = {**config, "target": target}
    standard_models: list[str] = []
    if task_type is not None:
        await plugin_service.sync_plugins_to_db(db, registry)
        rows = await plugin_service.list_available(db, task_type)
        standard_models = sorted(
            row.key for row in rows if tier_of(task_type, row.key) == "standard"
        )
    return AnalysisDraft(
        task_type=task_type if task_type in ("survival", "classification", "regression") else None,
        task_detection=det.to_dict() if task_type is not None else None,
        preprocess_config=config,
        standard_models=standard_models,
    )


@dataset_router.post("/{dataset_id}/research-profile", response_model=ResearchProfile)
async def get_research_profile(
    dataset_id: uuid.UUID,
    hints: ResearchHints | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResearchProfile:
    """分析数据集的研究设计，并推荐模型与投稿期刊方向。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    try:
        raw = storage_from_settings().get(key_from_uri(dataset.storage_uri))
        dataframe = parser.parse(raw, dataset.source_type).df
    except Exception as exc:
        raise AppError(
            code="DATASET_PARSE_FAILED",
            status=400,
            message="数据集无法解析，暂时无法生成研究画像",
        ) from exc
    result = detect_research_direction(
        dataframe, hints.model_dump(exclude_none=True) if hints is not None else None
    )
    # T6.7：研究画像 LLM 增强（分功能开关门控；失败回退纯规则结果，不阻塞）
    cfg = await settings_service.get_llm_config(db)
    switch = cfg.feature_switches.get("research_profile", "off")
    questions = None
    if switch != "off":
        facts = {
            **result,
            "n_rows": len(dataframe),
            "n_columns": len(dataframe.columns),
            "columns": [str(c) for c in dataframe.columns][:50],
        }
        service = init_llm_service_from_runtime(cfg)
        questions = await to_thread.run_sync(
            llm_tasks.generate_research_questions, service, facts, switch, cfg.temperature
        )
    result["research_questions"] = questions
    return ResearchProfile.model_validate(result)


@dataset_router.get("/{dataset_id}/research-templates", response_model=ResearchTemplatesResponse)
async def get_research_templates(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResearchTemplatesResponse:
    """T6.9 科研流程模板库：四类模板按数据集真实统计给出适用性与样本量核对。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    try:
        raw = storage_from_settings().get(key_from_uri(dataset.storage_uri))
        dataframe = parser.parse(raw, dataset.source_type).df
    except Exception as exc:
        raise AppError(
            code="DATASET_PARSE_FAILED",
            status=400,
            message="数据集无法解析，暂时无法评估研究模板",
        ) from exc
    templates = await to_thread.run_sync(evaluate_templates, dataframe)
    return ResearchTemplatesResponse.model_validate({"templates": templates})


async def _load_dataframe(
    dataset_id: uuid.UUID, user: CurrentUser, db: AsyncSession
) -> pd.DataFrame:
    """数据集 → DataFrame（T6.10 筛选/亚组端点共用）；404/400 在此抛出。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    try:
        raw = storage_from_settings().get(key_from_uri(dataset.storage_uri))
        return parser.parse(raw, dataset.source_type).df
    except Exception as exc:
        raise AppError(
            code="DATASET_PARSE_FAILED",
            status=400,
            message="数据集无法解析，暂时无法执行该分析",
        ) from exc


@dataset_router.post("/{dataset_id}/univariate-screen", response_model=UnivariateScreenResult)
async def post_univariate_screen(
    dataset_id: uuid.UUID,
    body: UnivariateScreenRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnivariateScreenResult:
    """T6.10 单因素筛选：逐特征关联检验，p<alpha 入选供多因素建模。"""
    dataframe = await _load_dataframe(dataset_id, user, db)
    try:
        result = await to_thread.run_sync(
            lambda: univariate_screen(
                dataframe,
                task_type=body.task_type,
                label_col=body.label_col,
                time_col=body.time_col,
                event_col=body.event_col,
                features=body.features,
                alpha=body.alpha,
            )
        )
    except ValueError as exc:
        raise AppError(code="SCREENING_INVALID", status=400, message=str(exc)) from exc
    return UnivariateScreenResult.model_validate(result)


@dataset_router.post("/{dataset_id}/subgroup-analysis", response_model=SubgroupAnalysisResult)
async def post_subgroup_analysis(
    dataset_id: uuid.UUID,
    body: SubgroupAnalysisRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubgroupAnalysisResult:
    """T6.10 亚组分析：分层暴露效应（OR/HR/β + 95%CI）+ 交互作用 p。"""
    dataframe = await _load_dataframe(dataset_id, user, db)
    try:
        result = await to_thread.run_sync(
            lambda: subgroup_analysis(
                dataframe,
                task_type=body.task_type,
                exposure=body.exposure,
                subgroup_vars=body.subgroup_vars,
                label_col=body.label_col,
                time_col=body.time_col,
                event_col=body.event_col,
            )
        )
    except ValueError as exc:
        raise AppError(code="SUBGROUP_INVALID", status=400, message=str(exc)) from exc
    return SubgroupAnalysisResult.model_validate(result)


@dataset_router.post("/{dataset_id}/quick-fix", response_model=DatasetVersion)
async def quick_fix(
    dataset_id: uuid.UUID,
    body: QuickFixRequest,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> DatasetVersion:
    """在线修复（docs/05 §5）：产生新版本，原文件不变，修复后重新校验。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    actions = [QuickFixAction(type=a.type, column=a.column, params=a.params) for a in body.actions]
    try:
        version = await quickfix_service.apply_quick_fix(
            db, storage_from_settings(), dataset=dataset, actions=actions
        )
    except ValueError as exc:
        raise AppError(code="VALIDATION_ERROR", status=400, message=str(exc)) from exc
    await audit_service.record(
        db,
        "dataset.quick_fix",
        user_id=user.id,
        resource_type="dataset",
        resource_id=dataset.id,
        detail={"version_no": version.version_no, "actions": [a.type for a in body.actions]},
    )
    await db.commit()
    # 阶段 A：修复后重算数据体检（docs/08 §3.2）
    if dataset.status == "VALIDATED":
        auto_dataset_insight.delay(str(dataset.id))
    return DatasetVersion.model_validate(version, from_attributes=True)


@dataset_router.get("/{dataset_id}/versions", response_model=list[DatasetVersion])
async def list_versions(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DatasetVersion]:
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    versions = await quickfix_service.list_versions(db, dataset_id)
    return [DatasetVersion.model_validate(v, from_attributes=True) for v in versions]


@dataset_router.post("/{dataset_id}/preprocess/validate")
async def validate_preprocess_dsl(
    dataset_id: uuid.UUID,
    body: dict[str, Any],
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """预处理 DSL 即时校验（docs/14 §3；非法 DSL → 400 VALIDATION_ERROR，T3.1 DoD）。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    try:
        cfg = validate_dsl(body)
    except ValidationError as exc:
        raise AppError(
            code="VALIDATION_ERROR",
            status=400,
            message="预处理 DSL 校验失败",
            details={"errors": jsonable_encoder(exc.errors())},
        ) from exc
    return {"valid": True, "normalized": cfg.model_dump(mode="json")}


@dataset_router.post("/{dataset_id}/preprocess/recommend")
async def recommend_preprocess_dsl(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """推荐默认预处理配置（docs/14 §3，docs/06 §2；T3.5 生成器，T3.6「推荐配置」按钮）。

    P1-2：长表（RV801）自动回退 DataFrame 版推荐以产出 reshape 步骤。
    """
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    return {
        "config": await dataset_service.recommended_preprocess_dsl(
            db, dataset, storage_from_settings()
        )
    }


@dataset_router.post("/{dataset_id}/preparation/preview", response_model=PreparationPreview)
async def preparation_preview(
    dataset_id: uuid.UUID,
    body: PreparationPreviewRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreparationPreview:
    """数据准备预览（docs/05 §8）：扫描化验长表+诊断表，返回列识别/词条/建议默认值。"""
    prev = await preparation_service.preview(
        db, storage_from_settings(), user, dataset_id, body.diagnosis_dataset_id
    )
    return PreparationPreview.model_validate(prev.to_dict())


@dataset_router.post(
    "/{dataset_id}/preparation/apply", status_code=202, response_model=PreparationJob
)
async def preparation_apply(
    dataset_id: uuid.UUID,
    body: PreparationApplyRequest,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> PreparationJob:
    """提交数据准备（docs/05 §8）：按决策异步生成宽表数据集，202 轮询 /preparations/{id}。"""
    job = await preparation_service.create_job(
        db, user, dataset_id, body.diagnosis_dataset_id, body.decisions
    )
    await audit_service.record(
        db,
        "preparation.apply",
        user_id=user.id,
        resource_type="preparation_job",
        resource_id=job.id,
        detail={"lab_dataset_id": str(dataset_id), "decisions": job.decisions},
    )
    await db.commit()
    try:
        run_preparation.delay(str(job.id))
    except Exception as exc:
        job.status = "FAILED"
        job.error = f"任务派发失败：{exc}"[:2000]
        await db.commit()
        raise AppError("TASK_DISPATCH_FAILED", 503, "数据准备任务暂时无法排队，请稍后重试") from exc
    await db.refresh(job)  # eager/快任务下回读最新状态；异步部署下仍为 PENDING
    return PreparationJob.model_validate(job, from_attributes=True)


@preparation_router.get("/{preparation_id}", response_model=PreparationJob)
async def get_preparation_job(
    preparation_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreparationJob:
    job = await preparation_service.get_job(db, user, preparation_id)
    if job is None:
        raise not_found("preparation", str(preparation_id))
    return PreparationJob.model_validate(job, from_attributes=True)


@dataset_router.post("/{dataset_id}/detect-task")
async def detect_dataset_task(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """任务类型自动识别（docs/14 §3 TaskDetectionResult；识别失败 422，docs/08 §1.1）。"""
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    if not dataset.column_profile:
        raise AppError(
            code="VALIDATION_ERROR",
            status=400,
            message="数据集尚未完成验证，请等待验证完成后再进行任务识别",
        )
    detection = detect_task_from_profile(dataset.column_profile)
    if detection.recommended_task is None:
        raise AppError(
            code="TASK_DETECTION_FAILED",
            status=422,
            message=detection.reason,
            details={"candidates": detection.to_dict()["candidates"]},
        )
    return detection.to_dict()
