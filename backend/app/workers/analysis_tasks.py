"""分析运行编排（docs/08 §2-3）：chain(preprocess → chord(models, comparison))。

- preprocess_run：解析原始数据 → run_preprocess 全量拟合 → 特征矩阵/原始特征/目标
  parquet 落存储 + PreprocessSnapshot → 状态 MODELING；异常 → FAILED。
- run_model：每折重建预处理 Pipeline（防泄漏，docs/06 §4）→ adapter fit/evaluate
  → 指标 {mean, std, folds}（docs/04 §3）→ 全量 fit → explain/artifacts → ModelResult；
  单模型异常只落 FAILED，不影响其他模型（docs/07 §4）。
- compare_run：chord 回调；主指标 mean 排名 → Comparison；全部失败 → run FAILED。
- 进度由 services.analysis.compute_progress 按 DB 状态推导（08 §3 公式）。
"""

import hashlib
import io
import time
import uuid
from typing import Any

import numpy as np
import pandas as pd
from celery import chain, chord
from sksurv.util import Surv
from sqlalchemy import delete, select

from app.core.logging import get_logger
from app.engines import parser
from app.engines.model_registry import ModelRegistry
from app.engines.pipeline import build_pipeline, iter_cv_splits, run_preprocess
from app.engines.preprocessing import validate_dsl
from app.models.entities import (
    AnalysisRun,
    Comparison,
    Dataset,
    DatasetVersion,
    ModelResult,
    PreprocessSnapshot,
)
from app.services.storage import key_from_uri, storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)

_registry: ModelRegistry | None = None

_PRIMARY_METRIC = {"survival": "c_index", "classification": "auc", "regression": "rmse"}


def get_registry() -> ModelRegistry:
    """进程级注册表单例（entry_points 扫描一次）。"""
    global _registry
    if _registry is None:
        registry = ModelRegistry()
        registry.load()
        _registry = registry
    return _registry


def _put_df(storage: Any, key: str, df: pd.DataFrame) -> str:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return str(storage.put(key, io.BytesIO(buf.getvalue())))


def _get_df(storage: Any, key: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(storage.get(key)))


def _target_frame(df: pd.DataFrame, target: Any, task_type: str) -> tuple[pd.DataFrame, list[str]]:
    """按任务类型抽取目标列；返回 (target_df, 目标列名列表)。"""
    if task_type == "survival":
        cols = [target.time_col, target.event_col]
        return pd.DataFrame({"time": df[target.time_col], "event": df[target.event_col]}), cols
    return pd.DataFrame({"label": df[target.label_col]}), [target.label_col]


def _y_adapter(target: pd.DataFrame, task_type: str) -> Any:
    """adapter 视角的 y：survival → sksurv 结构化数组；其余 → label 数组。"""
    if task_type == "survival":
        return Surv.from_arrays(
            target["event"].astype(bool).to_numpy(), target["time"].astype(float).to_numpy()
        )
    return target["label"].to_numpy()


def _y_preprocess(target: pd.DataFrame, task_type: str) -> pd.Series | None:
    """预处理 fit 视角的 y（特征选择用）；survival 无连续标签 → None。"""
    if task_type == "survival":
        return None
    return target["label"]


def _stratify(target: pd.DataFrame, task_type: str) -> pd.Series | None:
    if task_type == "classification":
        return target["label"]
    if task_type == "survival":
        return target["event"]
    return None


def _aggregate_folds(folds: list[dict[str, float]]) -> dict[str, Any]:
    """折指标 → {metric: {mean, std, folds}}（docs/04 §3）。"""
    out: dict[str, Any] = {}
    for metric in folds[0]:
        values = [f[metric] for f in folds if metric in f]
        arr = np.asarray(values, dtype=float)
        out[metric] = {
            "mean": float(arr.mean()),
            "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "folds": [float(v) for v in values],
        }
    return out


@celery_app.task(name="app.workers.analysis_tasks.preprocess_run")
def preprocess_run(run_id: str) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        run = db.get(AnalysisRun, uuid.UUID(run_id))
        if run is None or run.status == "CANCELED":
            return
        run.status = "PREPROCESSING"
        db.commit()
        try:
            version = db.get(DatasetVersion, run.dataset_version_id)
            dataset = db.get(Dataset, version.dataset_id) if version is not None else None
            if version is None or dataset is None:
                raise ValueError("数据集版本不存在")
            storage = storage_from_settings()
            raw = storage.get(key_from_uri(version.storage_uri))
            df = parser.parse(raw, dataset.source_type).df

            cfg = validate_dsl(run.preprocess_config)
            target, target_cols = _target_frame(df, cfg.target, run.task_type)
            raw_features = df.drop(columns=target_cols)
            input_hash = hashlib.sha256(raw).hexdigest()
            result = run_preprocess(
                raw_features, cfg, y=_y_preprocess(target, run.task_type), input_hash=input_hash
            )

            base = f"runs/{run_id}"
            feature_uri = _put_df(storage, f"{base}/features.parquet", result.features)
            _put_df(storage, f"{base}/raw_features.parquet", raw_features)
            _put_df(storage, f"{base}/target.parquet", target)

            db.execute(delete(PreprocessSnapshot).where(PreprocessSnapshot.run_id == run.id))
            db.add(
                PreprocessSnapshot(
                    run_id=run.id,
                    steps=result.snapshot["steps"],
                    feature_matrix_uri=feature_uri,
                    input_hash=input_hash,
                )
            )
            run.status = "MODELING"
            db.commit()
            logger.info("preprocess_done", run_id=run_id, features=list(result.features.columns))
        except Exception as exc:
            db.rollback()
            run.status = "FAILED"
            run.error = f"preprocess 失败：{exc}"[:2000]
            db.commit()
            logger.error("preprocess_failed", run_id=run_id, error=str(exc))
            raise  # 终止 chain：chord 不再入队（08 §3 PREPROCESSING → FAILED 为终态）


@celery_app.task(name="app.workers.analysis_tasks.run_model")
def run_model(run_id: str, model_key: str) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        run = db.get(AnalysisRun, uuid.UUID(run_id))
        if run is None or run.status == "CANCELED":
            return
        row = db.execute(
            select(ModelResult).where(
                ModelResult.run_id == run.id, ModelResult.model_key == model_key
            )
        ).scalar_one_or_none()
        if row is None:
            row = ModelResult(run_id=run.id, model_key=model_key)
            db.add(row)
        row.status = "RUNNING"
        db.commit()

        started = time.perf_counter()
        try:
            storage = storage_from_settings()
            base = f"runs/{run_id}"
            raw_features = _get_df(storage, f"{base}/raw_features.parquet")
            target = _get_df(storage, f"{base}/target.parquet")
            cfg = validate_dsl(run.preprocess_config)
            y = _y_adapter(target, run.task_type)
            params = (run.model_params or {}).get(model_key, {})

            registry = get_registry()
            proto = registry.get(model_key)
            if proto is None:
                raise ValueError(f"模型 {model_key} 未注册")

            # 每折重建 Pipeline + 全新 adapter 实例（防泄漏/防状态串折）
            folds: list[dict[str, float]] = []
            splits = iter_cv_splits(raw_features, cfg.validation, _stratify(target, run.task_type))
            for train_idx, val_idx in splits:
                pipe = build_pipeline(cfg)
                X_train = pipe.fit_transform(
                    raw_features.iloc[train_idx], _y_preprocess(target, run.task_type)
                )
                X_val = pipe.transform(raw_features.iloc[val_idx])
                adapter = type(proto)()
                adapter.fit(X_train, y[train_idx], params)
                folds.append(adapter.evaluate(X_val, y[val_idx]))

            # 全量 fit：用 preprocess 阶段固化的特征矩阵；explain/artifacts 供报告引用
            features = _get_df(storage, key_from_uri(_feature_uri(db, run.id)))
            full = type(proto)()
            full.fit(features, y, params)
            artifacts = full.predict_artifacts(features, y)
            row.explainability = full.explain(features)

            row.status = "SUCCESS"
            row.metrics = _aggregate_folds(folds)
            row.artifacts = [artifacts] if artifacts else []
            row.error = None
            row.duration_ms = int((time.perf_counter() - started) * 1000)
            db.commit()
            logger.info("model_done", run_id=run_id, model_key=model_key)
        except Exception as exc:
            db.rollback()
            row.status = "FAILED"
            row.error = str(exc)[:2000]
            row.duration_ms = int((time.perf_counter() - started) * 1000)
            db.commit()
            logger.error("model_failed", run_id=run_id, model_key=model_key, error=str(exc))


def _feature_uri(db: Any, run_id: uuid.UUID) -> str:
    snapshot = db.execute(
        select(PreprocessSnapshot).where(PreprocessSnapshot.run_id == run_id)
    ).scalar_one()
    return str(snapshot.feature_matrix_uri)


@celery_app.task(name="app.workers.analysis_tasks.compare_run")
def compare_run(results: Any, run_id: str) -> None:
    """chord 回调：results 为 header 各任务返回值（本任务集均为 None，忽略）。"""
    factory = get_sync_session_factory()
    with factory() as db:
        run = db.get(AnalysisRun, uuid.UUID(run_id))
        if run is None or run.status == "CANCELED":
            return
        rows = db.execute(select(ModelResult).where(ModelResult.run_id == run.id)).scalars().all()
        succeeded = [r for r in rows if r.status == "SUCCESS"]
        if not succeeded:
            run.status = "FAILED"
            run.error = "全部模型失败"
            db.commit()
            logger.error("run_failed_all_models", run_id=run_id)
            return

        run.status = "COMPARING"
        db.commit()

        primary = _PRIMARY_METRIC[run.task_type]
        reverse = primary != "rmse"  # rmse 越小越好，其余越大越好

        def _key(r: ModelResult) -> float:
            return float((r.metrics or {}).get(primary, {}).get("mean", float("nan")))

        ranked = sorted(succeeded, key=_key, reverse=reverse)
        ranking = [r.model_key for r in ranked]
        recommendation = {
            "ranking": ranking,
            "top": [
                {
                    "model_key": r.model_key,
                    "rank": i + 1,
                    "reason": (
                        f"{primary}={_key(r):.4f}±"
                        f"{(r.metrics or {}).get(primary, {}).get('std', 0.0):.4f}"
                    ),
                }
                for i, r in enumerate(ranked[:3])
            ],
            "primary_metric": primary,
        }
        db.execute(delete(Comparison).where(Comparison.run_id == run.id))
        charts = _build_charts(run, succeeded)
        db.add(
            Comparison(
                run_id=run.id,
                ranking=ranking,
                recommendation=recommendation,
                comparison_charts=charts,
            )
        )
        run.status = "COMPLETED"
        run.finished_at = func_now(db)
        db.commit()
        logger.info("run_completed", run_id=run_id, ranking=ranking)


def _build_charts(run: AnalysisRun, succeeded: list[ModelResult]) -> list[dict[str, Any]]:
    """对比图表装配（docs/09 §3 单数据源）；图表失败不阻断 compare（降级为空图表列表）。"""
    from app.engines.comparison.charts import build_comparison_charts

    try:
        prevalence: float | None = None
        if run.task_type == "classification":
            storage = storage_from_settings()
            target = _get_df(storage, f"runs/{run.id}/target.parquet")
            prevalence = float(target["label"].mean())
        payload = [
            {
                "model_key": r.model_key,
                "metrics": r.metrics or {},
                "artifacts": (r.artifacts or [{}])[0],
                "explainability": r.explainability,
            }
            for r in succeeded
        ]
        return build_comparison_charts(run.task_type, payload, prevalence=prevalence)
    except Exception as exc:
        logger.error("charts_build_failed", run_id=str(run.id), error=str(exc))
        return []


def func_now(db: Any) -> Any:
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    return db.execute(sa_select(func.now())).scalar_one()


def dispatch_analysis_run(run_id: str, model_keys: list[str]) -> str:
    """chain(preprocess → chord(models, comparison)) 入队；返回 chain id。"""
    workflow = chain(
        preprocess_run.si(run_id),
        chord(
            (run_model.si(run_id, key) for key in model_keys),
            compare_run.s(run_id),
        ),
    )
    result = workflow.apply_async()
    return str(result.id)


def dispatch_model_rerun(run_id: str, model_key: str) -> str:
    """单模型重跑：chain(run_model → compare_run) 入队（08 §3 重跑后重算比较）。"""
    workflow = chain(run_model.si(run_id, model_key), compare_run.s(run_id))
    result = workflow.apply_async()
    return str(result.id)


@celery_app.task(name="app.workers.analysis_tasks.janitor_sweep")
def janitor_sweep() -> dict[str, int]:
    """巡检（docs/12 §3 beat 每 5min；docs/20 R1）：

    - 超时 RUNNING 模型结果 → FAILED（worker kill -9 恢复）；
    - MODELING 且全部模型终态但回调未触发 → 手动补触发 compare；
    - 陈旧 PREPROCESSING / COMPARING / MODELING（无终态）→ FAILED。
    """
    from datetime import UTC, datetime, timedelta

    from app.core.config import get_settings

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        seconds=get_settings().model_timeout_s
    )
    stats = {"stale_models_failed": 0, "compare_recovered": 0, "runs_failed": 0}
    factory = get_sync_session_factory()
    recovered: list[str] = []
    with factory() as db:
        stale_results = (
            db.execute(
                select(ModelResult).where(
                    ModelResult.status == "RUNNING", ModelResult.created_at < cutoff
                )
            )
            .scalars()
            .all()
        )
        for r in stale_results:
            r.status = "FAILED"
            r.error = "janitor：任务超时（worker 可能已宕机）"
            stats["stale_models_failed"] += 1

        active_runs = (
            db.execute(
                select(AnalysisRun).where(
                    AnalysisRun.status.in_(("PREPROCESSING", "MODELING", "COMPARING"))
                )
            )
            .scalars()
            .all()
        )
        for run in active_runs:
            stale = bool(run.created_at < cutoff)
            if run.status != "MODELING":
                if stale:
                    run.status = "FAILED"
                    run.error = "janitor：运行超时"
                    run.finished_at = func_now(db)
                    stats["runs_failed"] += 1
                continue
            rows = (
                db.execute(select(ModelResult).where(ModelResult.run_id == run.id)).scalars().all()
            )
            states = {r.model_key: r.status for r in rows}
            terminal = ("SUCCESS", "FAILED", "SKIPPED")
            if all(states.get(k) in terminal for k in run.selected_models):
                recovered.append(str(run.id))  # R1 降级：回调未触发，提交后手动 compare
                stats["compare_recovered"] += 1
            elif stale:
                run.status = "FAILED"
                run.error = "janitor：运行超时"
                run.finished_at = func_now(db)
                stats["runs_failed"] += 1
        db.commit()

    for rid in recovered:
        compare_run.apply_async(args=[[], rid])
    if any(stats.values()):
        logger.warning("janitor_sweep", **stats)
    return stats
