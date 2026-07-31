"""分析运行端点（冻结契约 docs/14 §3 /analysis-runs）。

创建：POST /analysis-runs → 202（落库 PENDING + dispatch chain(preprocess→chord)）；
查询：GET /projects/{id}/analysis-runs 列表、GET /analysis-runs/{id} 详情、
GET /analysis-runs/{id}/progress 进度（docs/08 §3 公式推导）。
T5.9：POST /{id}/cancel（取消，DB 状态闸 + best-effort revoke）、
POST /{id}/models/{key}/rerun（单模型重跑 → 重算 comparison）。comparison 见 T6.x。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_registry, require_role
from app.core.logging import get_logger
from app.db import get_db
from app.engines.model_registry import ModelRegistry
from app.schemas.analysis import (
    AnalysisRunCreate,
    AnalysisRunDetail,
    AnalysisRunOut,
    ComparisonResult,
    RunProgress,
)
from app.schemas.auth import CurrentUser
from app.services import analysis as analysis_service
from app.services import audit as audit_service
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
    run.celery_chain_id = dispatch_analysis_run(str(run.id), list(body.selected_models))
    await db.commit()
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
    run.celery_chain_id = dispatch_model_rerun(str(run.id), model_key)
    await db.commit()
    return {"status": "MODELING"}
