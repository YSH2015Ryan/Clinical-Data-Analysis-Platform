"""分析运行服务（docs/08 §3-4、docs/14）：创建/查询/进度聚合。

- 状态机推进在 workers/analysis_tasks；本服务只做创建校验与读侧聚合。
- 进度按 docs/08 §3 公式由 DB 状态推导：preprocess 20% + 每模型 70%/N + comparison 10%。
- 模型可用性以 model_plugins 表为准（同步自注册表）：禁用/任务不匹配 → PLUGIN_UNAVAILABLE。
"""

import uuid
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, forbidden, not_found
from app.engines import parser
from app.engines.model_registry import ModelRegistry
from app.engines.preprocessing import PreprocessConfig, validate_dsl
from app.models.entities import (
    AnalysisRun,
    Comparison,
    Dataset,
    DatasetVersion,
    ModelPlugin,
    ModelResult,
    Project,
)
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.auth import CurrentUser
from app.services.plugins import sync_plugins_to_db
from app.services.storage import key_from_uri, storage_from_settings

TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELED")
_FINISHED_MODEL = ("SUCCESS", "FAILED", "SKIPPED")


def _check_target(task_type: str, target: dict[str, Any]) -> None:
    if task_type == "survival":
        if not (target.get("time_col") and target.get("event_col")):
            raise AppError(
                "VALIDATION_ERROR",
                400,
                "生存分析需要每位患者的「随访时间」列和「结局事件」列，当前未指定。"
                "如果研究问题是「是否患病/是否恶性」这类是非判断，请改用「分类 / 风险预测」。",
            )
    elif not target.get("label_col"):
        raise AppError(
            "VALIDATION_ERROR",
            400,
            f"任务类型 {task_type} 需要指定「结局列」（如 label/是否复发），当前未指定。",
        )


# 与 engines/columns.py _NUMERIC_PARSE_RATIO 同口径：字符串列 ≥90% 可转数值 → 视为数值意图
_NUMERIC_PARSE_RATIO = 0.9


def _check_target_data(
    version: DatasetVersion, dataset: Dataset, task_type: str, cfg: PreprocessConfig
) -> None:
    """数据级硬校验（docs/06 §2，2026-08-10）：只拦截数学上必然失败的情形。

    1. target 列存在性（三任务通用，列名笔误 otherwise 必在 worker 阶段失败）；
    2. 回归 + 非数值结局（既非数值 dtype 且可强制转数值比例 <90%）；
    3. 分类 + 有效类别 <2；
    4. 分类 + stratified_kfold 且最小类别样本数 < n_splits（分层抽样必然报错）。
    方法学层面的建议（如低基数回归）不在此拦截，由任务识别推荐层软提示。
    """
    target = cfg.target
    if task_type == "survival":
        cols = [c for c in (target.time_col, target.event_col) if c]
    else:
        cols = [target.label_col] if target.label_col else []
    if not cols:
        return  # target 缺失由 _check_target 先行拦截
    raw = storage_from_settings().get(key_from_uri(version.storage_uri))
    try:
        df = parser.parse(raw, dataset.source_type).df
    except Exception as exc:
        raise AppError(
            "VALIDATION_ERROR", 400, "数据集文件读取失败，请重新上传或联系管理员"
        ) from exc
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise AppError(
            "VALIDATION_ERROR",
            400,
            f"结局相关列 {missing} 在数据集中不存在，请核对预处理配置中的列名与数据文件一致。",
        )
    if task_type == "survival":
        time_values = pd.to_numeric(df[cols[0]], errors="coerce")
        event_values = pd.to_numeric(df[cols[1]], errors="coerce")
        if time_values.isna().any() or event_values.isna().any():
            raise AppError("VALIDATION_ERROR", 400, "生存时间和事件列不能包含缺失或非数值值")
        if (time_values <= 0).any():
            raise AppError("VALIDATION_ERROR", 400, "生存时间必须为正数")
        if not set(event_values.astype(int).unique()) <= {0, 1}:
            raise AppError("VALIDATION_ERROR", 400, "事件列必须只包含 0/1")
        return

    label_col = cols[0]
    if df[label_col].isna().any():
        raise AppError(
            "VALIDATION_ERROR",
            400,
            f"结局列「{label_col}」包含 {int(df[label_col].isna().sum())} 个缺失值，"
            "请先在数据质量页面处理后再建模。",
        )
    y = df[label_col]
    if task_type == "regression":
        if not pd.api.types.is_numeric_dtype(y):
            ratio = float(pd.to_numeric(y, errors="coerce").notna().mean()) if len(y) else 0.0
            if ratio < _NUMERIC_PARSE_RATIO:
                raise AppError(
                    "VALIDATION_ERROR",
                    400,
                    f"回归任务的结局列「{label_col}」必须是数值（如血压、评分），"
                    "当前列以文字类别为主。如果研究问题是「是否/属于哪类」的判断，"
                    "请改用「分类 / 风险预测」。",
                )
        return

    counts = y.value_counts()
    if len(counts) < 2:
        raise AppError(
            "VALIDATION_ERROR",
            400,
            f"结局列「{label_col}」只有一个有效取值，"
            "分类任务需要至少两个类别（如 患病/未患病），请核对结局定义。",
        )
    n_splits = cfg.validation.n_splits
    if cfg.validation.strategy == "stratified_kfold" and int(counts.min()) < n_splits:
        rare = counts.idxmin()
        raise AppError(
            "VALIDATION_ERROR",
            400,
            f"结局列中类别「{rare}」仅有 {int(counts.min())} 例，"
            f"少于交叉验证折数 {n_splits}，分层抽样无法进行。"
            "请减少折数、改用 kfold，或先合并稀有类别。",
        )


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
        await db.execute(
            select(Dataset).where(Dataset.id == version.dataset_id, Dataset.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if dataset is None:
        raise not_found("dataset", str(body.dataset_version_id))
    project = (
        await db.execute(select(Project).where(Project.id == dataset.project_id))
    ).scalar_one_or_none()
    if project is None or project.deleted_at is not None:
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
    # 验证策略与任务一致性（docs/06 §2）：回归无类别可分层，stratified_kfold 必然失败，
    # 落库前强制降级为 kfold
    if body.task_type == "regression" and cfg.validation.strategy == "stratified_kfold":
        cfg.validation.strategy = "kfold"
    _check_target_data(version, dataset, body.task_type, cfg)

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

    effective_params = {
        key: {**dict(plugins[key].default_params), **dict(body.model_params.get(key, {}))}
        for key in body.selected_models
    }

    run = AnalysisRun(
        project_id=project.id,
        dataset_version_id=version.id,
        task_type=body.task_type,
        status="PENDING",
        preprocess_config=cfg.model_dump(mode="json"),
        selected_models=list(body.selected_models),
        # 将管理员默认参数和本次覆盖快照进 run，后续修改插件不会改变历史结果。
        model_params=effective_params,
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
    if (
        project is None
        or project.deleted_at is not None
        or (user.role != "admin" and project.owner_id != user.id)
    ):
        raise forbidden()
    return run


async def get_run_dataset(db: AsyncSession, run: AnalysisRun) -> Dataset | None:
    """运行 → 源数据集（经 dataset_version；T6.13 迭代问答取列清单用）。"""
    version = await db.get(DatasetVersion, run.dataset_version_id)
    if version is None:
        return None
    return await db.get(Dataset, version.dataset_id)


async def list_runs(
    db: AsyncSession, user: CurrentUser, project_id: uuid.UUID
) -> list[AnalysisRun]:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None or project.deleted_at is not None:
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


async def get_comparison(db: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> dict[str, Any]:
    """ComparisonResult 聚合（docs/14）：性能表（含失败标注）+ 排名/推荐/图表。

    Comparison 行仅在 compare 完成后存在；未完成/失败 run 返回空 ranking，
    性能表照常返回（失败模型 metrics=None + error 标注，T6.1 DoD）。
    """
    run = await get_run(db, user, run_id)
    results = (
        (await db.execute(select(ModelResult).where(ModelResult.run_id == run.id))).scalars().all()
    )
    by_key = {r.model_key: r for r in results}
    table = [
        {
            "model_key": r.model_key,
            "status": r.status,
            "metrics": r.metrics if r.status == "SUCCESS" else None,
            "error": r.error,
            "duration_ms": r.duration_ms,
        }
        for key in run.selected_models
        if (r := by_key.get(key)) is not None
    ]
    comparison = (
        await db.execute(select(Comparison).where(Comparison.run_id == run.id))
    ).scalar_one_or_none()
    return {
        "table": table,
        "ranking": list(comparison.ranking) if comparison else [],
        "recommendation": dict(comparison.recommendation) if comparison else {},
        "charts": list(comparison.comparison_charts) if comparison else [],
    }


async def run_progress(db: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> dict[str, Any]:
    """进度查询：校验归属后按 docs/08 §3 公式聚合 DB 状态。"""
    run = await get_run(db, user, run_id)
    results = (
        (await db.execute(select(ModelResult).where(ModelResult.run_id == run.id))).scalars().all()
    )
    return compute_progress(run, list(results))


async def cancel_run(db: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> AnalysisRun:
    """取消运行（docs/08 §3）：终态拒绝；非终态模型结果置 SKIPPED。

    worker 各任务入口检查 run.status == "CANCELED" 提前返回（取消即时生效的 DB 闸）；
    revoke 由调用方（api 层）best-effort 执行。
    """
    run = await get_run(db, user, run_id)
    if run.status in TERMINAL_STATUSES:
        raise AppError("INVALID_RUN_STATE", 400, f"状态 {run.status} 不可取消")
    run.status = "CANCELED"
    run.finished_at = (await db.execute(select(func.now()))).scalar_one()
    running = (
        (
            await db.execute(
                select(ModelResult).where(
                    ModelResult.run_id == run.id, ModelResult.status.in_(("PENDING", "RUNNING"))
                )
            )
        )
        .scalars()
        .all()
    )
    for r in running:
        r.status = "SKIPPED"
        r.error = "运行已取消"
    return run


async def prepare_model_rerun(
    db: AsyncSession, user: CurrentUser, run_id: uuid.UUID, model_key: str
) -> AnalysisRun:
    """单模型重跑前置（docs/08 §3）：仅终态 run 且 model_key 在所选列表内。

    状态拨回 MODELING 供进度聚合；编排（run_model → compare）由调用方 dispatch。
    """
    run = await get_run(db, user, run_id)
    if run.status not in TERMINAL_STATUSES:
        raise AppError("INVALID_RUN_STATE", 400, f"状态 {run.status} 不可单模型重跑")
    if model_key not in run.selected_models:
        raise AppError("VALIDATION_ERROR", 400, f"模型 {model_key} 不在所选模型列表")
    run.status = "MODELING"
    run.error = None
    run.finished_at = None
    return run


def compute_progress(run: AnalysisRun, results: list[ModelResult]) -> dict[str, Any]:
    """进度聚合（docs/08 §3-4）：percent = preprocess 20% + 每模型 70%/N + comparison 10%。

    errors：FAILED 模型的错误信息（docs/14 RunProgress.errors，前端失败 tooltip）。
    """
    models: dict[str, str] = {k: "PENDING" for k in run.selected_models}
    errors: dict[str, str] = {}
    for r in results:
        models[r.model_key] = r.status
        if r.status == "FAILED" and r.error:
            errors[r.model_key] = r.error

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
        "errors": errors,
    }
