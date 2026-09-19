"""Analysis Manifest 引擎（P3-05，updateplan §78）。

§78 契约：每次分析产出独立 manifest JSON 工件——dataset_hash / analysis_version /
random_seed / validation(strategy+folds) / target / excluded_variables /
model_parameters；叠加 §77 可复现字段（分析 ID / 时间戳 / 软件版本 / 结果摘要）。

纯函数、确定性：输入全部来自 DB/存储真实记录，输出不含任何新计算数值
（结果摘要仅引用已持久化的 ranking/metrics 均值）。工件可下载用于复现核对。
"""

from typing import Any

MANIFEST_SCHEMA_VERSION = "1.0"


def _excluded_variables(
    preprocess_steps: list[dict[str, Any]] | None,
    transform_log: list[dict[str, Any]] | None,
) -> list[str]:
    """被排除变量 = 预处理 drop_columns 步骤 + 体检 quickfix drop_column 动作的并集（排序去重）。"""
    excluded: set[str] = set()
    for step in preprocess_steps or []:
        if step.get("type") == "drop_columns":
            for col in (step.get("params") or {}).get("columns") or []:
                excluded.add(str(col))
    for entry in transform_log or []:
        for action in entry.get("actions") or []:
            if action.get("type") == "drop_column" and action.get("column"):
                excluded.add(str(action["column"]))
    return sorted(excluded)


def _result_summary(comparison: dict[str, Any] | None) -> dict[str, Any] | None:
    """结果摘要：仅引用 comparison 已持久化的排名/推荐（不重新计算）。"""
    if not comparison:
        return None
    recommendation = comparison.get("recommendation") or {}
    top = (recommendation.get("top") or [None])[0]
    return {
        "primary_metric": recommendation.get("primary_metric"),
        "ranking": list(comparison.get("ranking") or []),
        "top_model": (top or {}).get("model_key"),
        "top_reason": (top or {}).get("reason"),
    }


def build_manifest(
    *,
    run: dict[str, Any],
    dataset: dict[str, Any],
    input_hash: str | None,
    preprocess_steps: list[dict[str, Any]] | None,
    transform_log: list[dict[str, Any]] | None,
    results: list[dict[str, Any]],
    comparison: dict[str, Any] | None,
    software: dict[str, Any],
) -> dict[str, Any]:
    """装配 §78 manifest。所有字段来自真实记录；缺失字段为 None 而非编造。"""
    config = run.get("preprocess_config") or {}
    validation = config.get("validation") or {}
    model_params = run.get("model_params") or {}
    models = [
        {
            "model_key": str(r.get("model_key")),
            "status": r.get("status"),
            # 未显式传参的模型为空 dict（库默认参数），不编造具体取值
            "parameters": model_params.get(str(r.get("model_key"))) or {},
            "duration_ms": r.get("duration_ms"),
        }
        for r in results
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "analysis_id": run.get("id"),
        "analysis_version": software.get("app"),
        "task_type": run.get("task_type"),
        "status": run.get("status"),
        "exploratory_mode": bool(run.get("exploratory_mode")),
        "created_at": run.get("created_at"),
        "finished_at": run.get("finished_at"),
        "dataset": {
            "name": dataset.get("name"),
            "dataset_id": dataset.get("id"),
            "version_no": dataset.get("version_no"),
            "dataset_hash": input_hash,
        },
        "random_seed": validation.get("seed"),
        "validation": {
            "strategy": validation.get("strategy"),
            "folds": validation.get("n_splits"),
            "seed": validation.get("seed"),
        },
        "target": config.get("target") or {},
        "excluded_variables": _excluded_variables(preprocess_steps, transform_log),
        "preprocess_steps": preprocess_steps or [],
        "models": models,
        "result_summary": _result_summary(comparison),
        "software": software,
    }
