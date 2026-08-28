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
from app.engines.failure import format_model_failure
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
    buf.seek(0)
    return str(storage.put(key, buf, buf.getbuffer().nbytes, "application/octet-stream"))


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
    # 统一编码，支持字符串标签和多分类；映射由整份目标列确定，折内不重新编码。
    return pd.Categorical(target["label"]).codes


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


def _oof_frame(oof: np.ndarray[Any, Any]) -> pd.DataFrame:
    """OOF 预测 → parquet 用 DataFrame：1D → 单列 oof；2D（多分类概率）→ oof_0..oof_k。"""
    if oof.ndim == 1:
        return pd.DataFrame({"oof": oof})
    return pd.DataFrame({f"oof_{i}": oof[:, i] for i in range(oof.shape[1])})


# T6.5：软时间限制分档——重模型（近似 O(n log n) 以上或原生迭代慢）给更长软限；
# 软限内在任务线程抛 SoftTimeLimitExceeded → 立即分类落 FAILED（不再等 janitor 轮询）。
_HEAVY_MODELS = {
    "rsf",
    "gbs",
    "svm",
    "catboost",
    "xgboost",
    "xgboost_reg",
    "lightgbm",
    "deepsurv",
    "gam",
    "gee",
    "dlnm",
}


def _model_soft_time_limit(model_key: str) -> int:
    """按模型分档的软时间限制（秒）；未知模型走默认档。

    软限须低于硬超时 model_timeout_s（否则 SIGKILL 先于 SoftTimeLimitExceeded，
    失去失败分类机会）；部署调低 MODEL_TIMEOUT_S 时随之下探，至少留 60s 余量。
    """
    from app.core.config import get_settings

    settings = get_settings()
    tier = (
        settings.model_soft_time_limit_heavy
        if model_key in _HEAVY_MODELS
        else settings.model_soft_time_limit_default
    )
    return int(min(tier, max(60, settings.model_timeout_s - 60)))


def _sign_model_tasks(run_id: str, model_keys: list[str]) -> list[Any]:
    """run_model 签名列表（携带按模型分档的 soft_time_limit 选项）。"""
    return [
        run_model.si(run_id, key).set(soft_time_limit=_model_soft_time_limit(key))
        for key in model_keys
    ]


def _wants_explain(proto: Any) -> bool:
    """全量 fit 是否必要（T6.5 消除双训练）：仅当模型产出可解释性内容时才需要。

    无 feature_importance/shap 能力且已有 OOF 时,artifacts 直接由 OOF 生成,
    跳过 K 折之外的全量 fit（如未来无解释产物的轻量模型;km 无 OOF 不受影响）。
    未声明 capabilities 的第三方插件保持保守（仍全量 fit,不丢 explainability）。
    """
    caps = getattr(proto, "capabilities", None)
    if caps is None:
        return True
    return bool(caps.get("feature_importance") or caps.get("shap"))


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
            if target.isna().any().any():
                missing = {str(k): int(v) for k, v in target.isna().sum().items() if int(v)}
                raise ValueError(f"结局列包含缺失值，不能直接建模：{missing}")
            if run.task_type == "survival":
                if (pd.to_numeric(target["time"], errors="coerce") <= 0).any():
                    raise ValueError("生存时间必须为正数")
                event = pd.to_numeric(target["event"], errors="coerce")
                if event.isna().any() or not set(event.astype(int).unique()) <= {0, 1}:
                    raise ValueError("事件列必须只包含 0/1")
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
        row.error = None  # 清掉上一轮遗留的 error，防止重跑后前端仍显示旧错误
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
            oof: np.ndarray[Any, Any] | None = (
                np.full(len(raw_features), np.nan, dtype=float)
                if run.task_type == "regression"
                else None
            )
            splits = iter_cv_splits(raw_features, cfg.validation, _stratify(target, run.task_type))
            for train_idx, val_idx in splits:
                pipe = build_pipeline(cfg)
                preprocess_y = _y_preprocess(target, run.task_type)
                X_train = pipe.fit_transform(
                    raw_features.iloc[train_idx],
                    preprocess_y.iloc[train_idx] if preprocess_y is not None else None,
                )
                X_val = pipe.transform(raw_features.iloc[val_idx])
                adapter = type(proto)()
                adapter.fit(X_train, y[train_idx], params)
                folds.append(adapter.evaluate(X_val, y[val_idx]))
                if oof is not None:
                    predict_values = getattr(adapter, "predict_values", None)
                    if predict_values is not None:
                        prediction = np.asarray(predict_values(X_val), dtype=float)
                        oof[val_idx] = prediction
                elif run.task_type == "classification":
                    predict_values = getattr(adapter, "predict_values", None)
                    if predict_values is not None:
                        prediction = np.asarray(predict_values(X_val), dtype=float)
                        if prediction.ndim == 1:
                            oof = np.full(len(raw_features), np.nan, dtype=float)
                        else:
                            oof = np.full(
                                (len(raw_features), prediction.shape[1]), np.nan, dtype=float
                            )
                        oof[val_idx] = prediction

            # 全量 fit：用 preprocess 阶段固化的特征矩阵；explain/artifacts 供报告引用。
            # T6.5：有 OOF 且模型无可解释性产物时跳过全量 fit（消除 K 折 + 全量双训练）。
            have_oof = oof is not None and not np.isnan(oof).any()
            if have_oof and not _wants_explain(proto):
                assert oof is not None  # mypy: have_oof 已含非 None 判定
                artifacts = type(proto)().predict_artifacts_from_predictions(oof, y)
                _put_df(storage, f"{base}/oof_{model_key}.parquet", _oof_frame(oof))
                row.explainability = None
            else:
                features = _get_df(storage, key_from_uri(_feature_uri(db, run.id)))
                full = type(proto)()
                full.fit(features, y, params)
                if have_oof:
                    assert oof is not None  # mypy: have_oof 已含非 None 判定
                    artifacts = full.predict_artifacts_from_predictions(oof, y)
                    # T6.3：OOF 持久化（报告回归诊断/校准检验的数据源；幂等覆盖）
                    _put_df(storage, f"{base}/oof_{model_key}.parquet", _oof_frame(oof))
                else:
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
            # T6.5：失败原因分类化（超时/内存/未收敛/数据不适配）+ 用户可读建议
            row.error = format_model_failure(exc)[:2000]
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

        # 加权排名 + 理由模板（docs/09 §4）；权重取配置
        from app.core.config import get_settings
        from app.engines.comparison.ranking import build_recommendation

        settings = get_settings()
        weights = {
            "primary": settings.ranking_weight_primary,
            "stability": settings.ranking_weight_stability,
            "secondary": settings.ranking_weight_secondary,
        }
        payload = [{"model_key": r.model_key, "metrics": r.metrics or {}} for r in succeeded]
        recommendation = build_recommendation(run.task_type, payload, weights=weights)
        ranking: list[str] = recommendation["ranking"]
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
            # 从已落库的混淆矩阵推算阳性率（避免重新读取大文件）
            # 仅二分类有意义（DCA 需要阳性率）；多分类 prevalence 保持 None
            for r in succeeded:
                arts = (r.artifacts or [{}])[0]
                cm = arts.get("confusion_matrix", {})
                labels = cm.get("labels", [])
                matrix = cm.get("matrix", [])
                if len(labels) == 2 and matrix:
                    total = sum(sum(row) for row in matrix)
                    positives = sum(matrix[1]) if len(matrix) > 1 else 0
                    if total > 0:
                        prevalence = positives / total
                    break
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
            _sign_model_tasks(run_id, model_keys),
            compare_run.s(run_id),
        ),
    )
    result = workflow.apply_async()
    return str(result.id)


def dispatch_model_rerun(run_id: str, model_key: str) -> str:
    """单模型重跑：chain(run_model → compare_run) 入队（08 §3 重跑后重算比较）。"""
    workflow = chain(
        run_model.si(run_id, model_key).set(soft_time_limit=_model_soft_time_limit(model_key)),
        compare_run.s(run_id),
    )
    result = workflow.apply_async()
    return str(result.id)


@celery_app.task(name="app.workers.analysis_tasks.janitor_sweep")
def janitor_sweep() -> dict[str, int]:
    """巡检（docs/12 §3 beat 每 5min；docs/20 R1）：

    - 超时 RUNNING 模型结果 → FAILED（worker kill -9 恢复）；
    - MODELING 且全部模型终态但回调未触发 → 手动补触发 compare；
    - 陈旧 PREPROCESSING / COMPARING / MODELING（无终态）→ FAILED。

    超时语义：
    - model_timeout_s：单个 ModelResult 行从开始 RUNNING（updated_at）到现在超过此值即视为僵死；
      PREPROCESSING / COMPARING 是单任务阶段，同样按此值判定；
    - run_timeout_s：MODELING 阶段（多模型并行）从创建到现在超过此值且仍有模型未终态才视为超时；
      只要还有模型仍在 RUNNING（未被上面判定为僵死），就继续等待，不提前杀掉 run。
    """
    from datetime import UTC, datetime, timedelta

    from app.core.config import get_settings

    settings = get_settings()
    model_cutoff = datetime.now(UTC) - timedelta(seconds=settings.model_timeout_s)
    run_cutoff = datetime.now(UTC) - timedelta(seconds=settings.run_timeout_s)
    stats = {"stale_models_failed": 0, "compare_recovered": 0, "runs_failed": 0}
    factory = get_sync_session_factory()
    recovered: list[str] = []
    with factory() as db:
        stale_results = (
            db.execute(
                select(ModelResult).where(
                    ModelResult.status == "RUNNING", ModelResult.updated_at < model_cutoff
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
            run_stale = bool(run.created_at < run_cutoff)
            if run.status != "MODELING":
                # PREPROCESSING / COMPARING 是单任务阶段，按单任务超时（model_timeout_s）
                # 判定僵死（T5.9 契约；run_timeout_s 是整个 run 的预算，不适用于此）。
                if bool(run.created_at < model_cutoff):
                    run.status = "FAILED"
                    run.error = "janitor：运行超时"
                    run.finished_at = func_now(db)
                    stats["runs_failed"] += 1
                continue

            # MODELING：先检查各模型终态
            rows = (
                db.execute(select(ModelResult).where(ModelResult.run_id == run.id)).scalars().all()
            )
            states = {r.model_key: r.status for r in rows}
            terminal = ("SUCCESS", "FAILED", "SKIPPED")
            all_done = all(states.get(k) in terminal for k in run.selected_models)

            if all_done:
                # 所有模型已完成但 compare 回调未触发 → 手动补触发（R1 降级）
                recovered.append(str(run.id))
                stats["compare_recovered"] += 1
            elif run_stale:
                # 超过 run_timeout_s 且仍有模型未完成 → 整体超时
                run.status = "FAILED"
                run.error = "janitor：运行超时"
                run.finished_at = func_now(db)
                stats["runs_failed"] += 1
            # else: 仍在正常运行范围内，不干预
        db.commit()

    for rid in recovered:
        compare_run.apply_async(args=[[], rid])
    if any(stats.values()):
        logger.warning("janitor_sweep", **stats)
    return stats
