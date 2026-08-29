"""分析运行端点（冻结契约 docs/14 §3 /analysis-runs）。

创建：POST /analysis-runs → 202（落库 PENDING + dispatch chain(preprocess→chord)）；
查询：GET /projects/{id}/analysis-runs 列表、GET /analysis-runs/{id} 详情、
GET /analysis-runs/{id}/progress 进度（docs/08 §3 公式推导）。
T5.9：POST /{id}/cancel（取消，DB 状态闸 + best-effort revoke）、
POST /{id}/models/{key}/rerun（单模型重跑 → 重算 comparison）。comparison 见 T6.x。
"""

import uuid
from typing import Any

from anyio import to_thread
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_registry, require_role
from app.core.errors import AppError, not_found
from app.core.logging import get_logger
from app.db import get_db
from app.engines import parser
from app.engines.iteration import rule_based_advice
from app.engines.model_registry import ModelRegistry
from app.schemas.analysis import (
    AnalysisRunCreate,
    AnalysisRunDetail,
    AnalysisRunOut,
    ComparisonResult,
    IterateRequest,
    IterateResponse,
    RunProgress,
)
from app.schemas.auth import CurrentUser
from app.services import analysis as analysis_service
from app.services import audit as audit_service
from app.services import llm_tasks
from app.services import plugins as plugin_service
from app.services import settings as settings_service
from app.services.llm import init_llm_service_from_runtime
from app.services.storage import key_from_uri, storage_from_settings
from app.workers.analysis_tasks import dispatch_analysis_run, dispatch_model_rerun
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

router = APIRouter(tags=["analysis"])


@router.post("/analysis-runs", status_code=202, response_model=AnalysisRunOut)
async def create_analysis_run(
    body: AnalysisRunCreate,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> AnalysisRunOut:
    run = await analysis_service.create_run(db, user, body, registry=registry)
    await audit_service.record(
        db,
        "analysis.create",
        user_id=user.id,
        resource_type="analysis_run",
        resource_id=run.id,
        detail={"task_type": body.task_type, "models": list(body.selected_models)},
    )
    await db.commit()  # 先落库：worker 以独立会话读取 run 行
    try:
        run.celery_chain_id = dispatch_analysis_run(str(run.id), list(body.selected_models))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        # 任务代理不可用时不能留下永远 PENDING 的运行。
        run = await analysis_service.get_run(db, user, run.id)
        run.status = "FAILED"
        run.error = f"任务派发失败：{exc}"[:2000]
        await db.commit()
        raise AppError("TASK_DISPATCH_FAILED", 503, "分析任务暂时无法排队，请稍后重试") from exc
    return AnalysisRunOut(
        id=run.id, status=run.status, task_type=run.task_type, created_at=run.created_at
    )


@router.get("/projects/{project_id}/analysis-runs")
async def list_project_runs(
    project_id: uuid.UUID,
    status: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    runs = await analysis_service.list_runs(db, user, project_id)
    if status is not None:
        runs = [r for r in runs if r.status == status]
    return {
        "items": [
            AnalysisRunOut(id=r.id, status=r.status, task_type=r.task_type, created_at=r.created_at)
            for r in runs
        ],
        "next_cursor": None,
    }


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRunDetail)
async def get_analysis_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisRunDetail:
    run = await analysis_service.get_run(db, user, run_id)
    return AnalysisRunDetail(
        id=run.id,
        status=run.status,
        task_type=run.task_type,
        created_at=run.created_at,
        task_detection=run.task_detection,
        error=run.error,
    )


@router.get("/analysis-runs/{run_id}/progress", response_model=RunProgress)
async def get_run_progress(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunProgress:
    return RunProgress(**await analysis_service.run_progress(db, user, run_id))


@router.get("/analysis-runs/{run_id}/comparison", response_model=ComparisonResult)
async def get_run_comparison(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ComparisonResult:
    return ComparisonResult(**await analysis_service.get_comparison(db, user, run_id))


@router.post("/analysis-runs/{run_id}/cancel")
async def cancel_analysis_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    run = await analysis_service.cancel_run(db, user, run_id)
    await audit_service.record(
        db, "analysis.cancel", user_id=user.id, resource_type="analysis_run", resource_id=run.id
    )
    await db.commit()
    if run.celery_chain_id:
        try:  # best-effort：DB CANCELED 状态才是即时生效闸（worker 入口检查）
            celery_app.control.revoke(run.celery_chain_id, terminate=True)
        except Exception as exc:
            logger.warning("revoke_failed", run_id=str(run_id), error=str(exc))
    return {"status": "CANCELED"}


@router.post("/analysis-runs/{run_id}/models/{model_key}/rerun", status_code=202)
async def rerun_model(
    run_id: uuid.UUID,
    model_key: str,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    run = await analysis_service.prepare_model_rerun(db, user, run_id, model_key)
    await audit_service.record(
        db,
        "analysis.rerun_model",
        user_id=user.id,
        resource_type="analysis_run",
        resource_id=run.id,
        detail={"model_key": model_key},
    )
    await db.commit()  # 先落 MODELING 状态：worker 以独立会话读取
    try:
        run.celery_chain_id = dispatch_model_rerun(str(run.id), model_key)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise AppError("TASK_DISPATCH_FAILED", 503, "重跑任务暂时无法排队，请稍后重试") from exc
    return {"status": "MODELING"}


@router.post("/analysis-runs/{run_id}/iterate", response_model=IterateResponse)
async def iterate_run(
    run_id: uuid.UUID,
    body: IterateRequest,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> IterateResponse:
    """T6.13 对话式迭代：回答「如果把 X 当协变量会怎样」并给结构化重跑建议。

    规则引擎兜底恒可用；iteration 分功能开关打开时 LLM 增强
    （列名/模型白名单 + 幻觉数值校验，不合格回退规则版，红线8）。
    """
    run = await analysis_service.get_run(db, user, run_id)
    dataset = await analysis_service.get_run_dataset(db, run)
    if dataset is None:
        raise not_found("dataset", str(run.dataset_version_id))

    available = await plugin_service.list_available(db, run.task_type)
    target = (run.preprocess_config or {}).get("target") or {}
    target_cols = {
        str(c)
        for c in (target.get("label_col"), target.get("time_col"), target.get("event_col"))
        if c
    }
    columns = [
        str(c.get("name"))
        for c in (dataset.column_profile or [])
        if c.get("name") and str(c.get("name")) not in target_cols
    ]
    if not columns:
        # 旧数据集无列画像：解析源文件表头兜底（只取列名元数据）
        try:
            raw = storage_from_settings().get(key_from_uri(dataset.storage_uri))
            columns = [
                str(c)
                for c in parser.parse(raw, dataset.source_type).df.columns
                if str(c) not in target_cols
            ]
        except Exception:
            columns = []
    comparison = await analysis_service.get_comparison(db, user, run_id)
    top = ((comparison.get("recommendation") or {}).get("top") or [{}])[0]
    metrics = {
        row["model_key"]: {
            k: v.get("mean")
            for k, v in (row.get("metrics") or {}).items()
            if isinstance(v, dict) and v.get("mean") is not None
        }
        for row in comparison.get("table") or []
        if row.get("metrics")
    }
    facts: dict[str, Any] = {
        "task_type": run.task_type,
        "available_columns": columns[:80],
        "available_models": [m.key for m in available],
        "selected_models": list(run.selected_models),
        "top_model": top.get("model_key"),
        "top_reason": top.get("reason"),
        "metrics": metrics,
    }

    base = rule_based_advice(body.question, facts)
    llm_out: dict[str, Any] | None = None
    cfg = await settings_service.get_llm_config(db)
    switch = cfg.feature_switches.get("iteration", "off")
    if switch != "off":
        service = init_llm_service_from_runtime(cfg)
        try:
            llm_out = await to_thread.run_sync(
                llm_tasks.generate_iteration_advice,
                service,
                body.question,
                facts,
                switch,
                cfg.temperature,
            )
        except Exception as exc:  # LLM 链路任何异常都不阻塞主流程（规则版兜底）
            logger.warning("iteration_llm_failed", run_id=str(run_id), error=str(exc))
    result = llm_out if llm_out is not None else base

    await audit_service.record(
        db,
        "analysis.iterate",
        user_id=user.id,
        resource_type="analysis_run",
        resource_id=run.id,
        detail={"question": body.question[:200], "llm_enhanced": llm_out is not None},
    )
    await db.commit()
    return IterateResponse(
        answer=result["answer"],
        suggestion=result.get("suggestion"),
        llm_enhanced=llm_out is not None,
        dataset_id=dataset.id,
        project_id=dataset.project_id,
    )
