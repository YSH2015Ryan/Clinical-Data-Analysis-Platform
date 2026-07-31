"""分析运行服务（docs/08 §3-4、docs/14）：创建/查询/进度聚合。

- 状态机推进在 workers/analysis_tasks；本服务只做创建校验与读侧聚合。
- 进度按 docs/08 §3 公式由 DB 状态推导：preprocess 20% + 每模型 70%/N + comparison 10%。
- 模型可用性以 model_plugins 表为准（同步自注册表）：禁用/任务不匹配 → PLUGIN_UNAVAILABLE。
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, forbidden, not_found
from app.engines.model_registry import ModelRegistry
from app.engines.preprocessing import validate_dsl
from app.models.entities import (
    AnalysisRun,
    Dataset,
    DatasetVersion,
    ModelPlugin,
    ModelResult,
    Project,
)
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.auth import CurrentUser
from app.services.plugins import sync_plugins_to_db

TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELED")
_FINISHED_MODEL = ("SUCCESS", "FAILED", "SKIPPED")


def _check_target(task_type: str, target: dict[str, Any]) -> None:
    if task_type == "survival":
        if not (target.get("time_col") and target.get("event_col")):
            raise AppError(
                "VALIDATION_ERROR", 400, "survival 任务须在 target 指定 time_col 与 event_col"
            )
    elif not target.get("label_col"):
        raise AppError("VALIDATION_ERROR", 400, f"{task_type} 任务须在 target 指定 label_col")


async def create_run(
    db: AsyncSession,
    user: CurrentUser,
    body: AnalysisRunCreate,
    *,
    registry: ModelRegistry,
) -> AnalysisRun:
    """创建 AnalysisRun（PENDING）；校验通过即落库，编排由调用方 dispatch。"""
    version = (
        await db.execute(select(DatasetVersion).where(DatasetVersion.id == body.dataset_version_id))
    ).scalar_one_or_none()
    if version is None:
        raise not_found("dataset", str(body.dataset_version_id))
    dataset = (
        await db.execute(select(Dataset).where(Dataset.id == version.dataset_id))
    ).scalar_one_or_none()
    if dataset is None:
        raise not_found("dataset", str(body.dataset_version_id))
    project = (
        await db.execute(select(Project).where(Project.id == dataset.project_id))
    ).scalar_one_or_none()
    if project is None:
        raise not_found("dataset", str(body.dataset_version_id))
    if user.role != "admin" and project.owner_id != user.id:
        raise forbidden()
    if dataset.status != "VALIDATED":
        raise AppError(
            "DATASET_NOT_READY", 400, f"数据集状态 {dataset.status}，须 VALIDATED 才可创建分析"
        )

    active = (
        await db.execute(
            select(func.count())
            .select_from(AnalysisRun)
            .join(DatasetVersion, AnalysisRun.dataset_version_id == DatasetVersion.id)
            .where(
                DatasetVersion.dataset_id == dataset.id,
                AnalysisRun.status.notin_(TERMINAL_STATUSES),
            )
        )
    ).scalar_one()
    if active:
        raise AppError("RUN_ALREADY_ACTIVE", 409, "同数据集已有进行中的分析")

    try:
        cfg = validate_dsl(body.preprocess_config)
    except Exception as exc:
        raise AppError("VALIDATION_ERROR", 400, f"preprocess_config 非法：{exc}") from exc
    _check_target(body.task_type, cfg.target.model_dump())

    # 模型可用性以 DB 为准（先同步注册表；禁用不被覆盖 docs/15 §1）
    await sync_plugins_to_db(db, registry)
    rows = (
        await db.execute(select(ModelPlugin).where(ModelPlugin.key.in_(body.selected_models)))
    ).scalars()
    plugins = {r.key: r for r in rows}
    for key in body.selected_models:
        plugin = plugins.get(key)
        if plugin is None or not plugin.enabled or body.task_type not in plugin.task_types:
            raise AppError(
                "PLUGIN_UNAVAILABLE",
                400,
                f"模型 {key} 不可用（未注册/已禁用/不支持 {body.task_type}）",
            )

    run = AnalysisRun(
        project_id=project.id,
        dataset_version_id=version.id,
        task_type=body.task_type,
        status="PENDING",
        preprocess_config=cfg.model_dump(mode="json"),
        selected_models=list(body.selected_models),
        model_params=dict(body.model_params),
        created_by=user.id,
    )
    db.add(run)
    await db.flush()
    return run


async def get_run(db: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> AnalysisRun:
    run = (
        await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        raise not_found("run", str(run_id))
    project = (
        await db.execute(select(Project).where(Project.id == run.project_id))
    ).scalar_one_or_none()
    if project is None or (user.role != "admin" and project.owner_id != user.id):
        raise forbidden()
    return run


async def list_runs(
    db: AsyncSession, user: CurrentUser, project_id: uuid.UUID
) -> list[AnalysisRun]:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise not_found("project", str(project_id))
    if user.role != "admin" and project.owner_id != user.id:
        raise forbidden()
    rows = (
        await db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.project_id == project_id)
            .order_by(AnalysisRun.created_at.desc())
        )
    ).scalars()
    return list(rows)


async def run_progress(db: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> dict[str, Any]:
    """进度查询：校验归属后按 docs/08 §3 公式聚合 DB 状态。"""
    run = await get_run(db, user, run_id)
    results = (
        (await db.execute(select(ModelResult).where(ModelResult.run_id == run.id))).scalars().all()
    )
    return compute_progress(run, list(results))


def compute_progress(run: AnalysisRun, results: list[ModelResult]) -> dict[str, Any]:
    """进度聚合（docs/08 §3-4）：percent = preprocess 20% + 每模型 70%/N + comparison 10%。"""
    models: dict[str, str] = {k: "PENDING" for k in run.selected_models}
    for r in results:
        models[r.model_key] = r.status

    n = max(len(run.selected_models), 1)
    done = sum(1 for k in run.selected_models if models.get(k) in _FINISHED_MODEL)
    status = run.status
    current_step: str | None = None

    if status == "PENDING":
        percent = 0
    elif status == "PREPROCESSING":
        percent, current_step = 10, "preprocess"
    elif status == "COMPARING":
        percent, current_step = 90, "comparison"
    elif status == "COMPLETED":
        percent = 100
    else:  # MODELING / FAILED / CANCELED：按已完成模型折算
        percent = 20 + round(70 * done / n)
        running = next((k for k in run.selected_models if models.get(k) == "RUNNING"), None)
        current_step = f"model:{running}" if running else None

    return {
        "status": status,
        "percent": min(percent, 100),
        "current_step": current_step,
        "models": models,
    }
