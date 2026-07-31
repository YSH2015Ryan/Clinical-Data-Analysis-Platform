"""对比图表数据装配（docs/09 §3、§6）：ModelResult 产物 → ChartAsset JSON。

单数据源原则：每图只生成一份数据 JSON，前端 ECharts 与报告 PNG 均由它渲染。
图表数据一律来自 SUCCESS 模型的真实计算产物（roc/calibration/km/HR/重要性），
不虚构任何数值（CLAUDE.md §8）。
"""

from typing import Any

import numpy as np

# docs/14 ChartAsset.kind 枚举对齐
_ROC, _CALIBRATION, _DCA = "roc", "calibration", "dca"
_CONFUSION, _KM, _CINDEX_FOREST = "confusion_matrix", "km", "cindex_forest"
_HR_FOREST, _FEATURE_IMPORTANCE = "hr_forest", "feature_importance"
_SCATTER = "prediction_scatter"

_MAX_POINTS = 100  # 曲线类图表抽稀上限（JSON 体积控制）
_TOP_FEATURES = 10  # 特征重要性并排对比的特征数（docs/09 §3 Top-N）


def _thin(xs: list[Any], ys_list: list[list[Any]]) -> tuple[list[Any], list[list[Any]]]:
    """等距抽稀曲线点至 _MAX_POINTS（保留首尾）。"""
    n = len(xs)
    if n <= _MAX_POINTS:
        return xs, ys_list
    idx = np.unique(np.linspace(0, n - 1, _MAX_POINTS).astype(int))
    return [xs[i] for i in idx], [[ys[i] for i in idx] for ys in ys_list]


def _importances_of(explainability: dict[str, Any] | None) -> dict[str, float] | None:
    """从 explainability 提取统一重要性字典；系数类取 |coef|。"""
    if not explainability:
        return None
    importances = explainability.get("importances")
    if isinstance(importances, dict) and importances:
        return {str(k): float(v) for k, v in importances.items()}
    if explainability.get("type") == "coefficients":
        table = explainability.get("table") or []
        return {str(r["feature"]): abs(float(r["coef"])) for r in table}
    return None


def _feature_importance_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Top-N 特征重要性并排对比（docs/09 §3）；各模型按自身最大值归一以便并排。"""
    per_model: dict[str, dict[str, float]] = {}
    for row in rows:
        imp = _importances_of(row.get("explainability"))
        if imp:
            per_model[row["model_key"]] = imp
    if not per_model:
        return None
    max_per_feature: dict[str, float] = {}
    for imp in per_model.values():
        for feature, value in imp.items():
            max_per_feature[feature] = max(max_per_feature.get(feature, 0.0), value)
    features = sorted(max_per_feature, key=lambda f: max_per_feature[f], reverse=True)[
        :_TOP_FEATURES
    ]
    series = []
    for model_key, imp in per_model.items():
        norm = max(imp.values()) or 1.0
        series.append(
            {
                "model_key": model_key,
                "values": [round(imp.get(f, 0.0) / norm, 6) for f in features],
            }
        )
    return {
        "kind": _FEATURE_IMPORTANCE,
        "title": f"特征重要性对比（Top {len(features)}，各模型归一化）",
        "data": {"features": features, "series": series},
        "image_uri": None,
    }


def _roc_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    series = []
    for row in rows:
        roc = row["artifacts"].get("roc_curve")
        if not roc:
            continue
        fpr, tpr = _thin(list(roc["fpr"]), [list(roc["tpr"])])
        auc = (row["metrics"] or {}).get("auc", {}).get("mean")
        series.append({"model_key": row["model_key"], "fpr": fpr, "tpr": tpr[0], "auc": auc})
    if not series:
        return None
    return {"kind": _ROC, "title": "ROC 曲线对比", "data": {"series": series}, "image_uri": None}


def _calibration_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    series = []
    for row in rows:
        cal = row["artifacts"].get("calibration_curve")
        if not cal:
            continue
        brier = (row["metrics"] or {}).get("brier", {}).get("mean")
        series.append(
            {
                "model_key": row["model_key"],
                "prob_true": list(cal["prob_true"]),
                "prob_pred": list(cal["prob_pred"]),
                "brier": brier,
            }
        )
    if not series:
        return None
    return {
        "kind": _CALIBRATION,
        "title": "校准曲线（reliability diagram）",
        "data": {"series": series},
        "image_uri": None,
    }


def _dca_chart(rows: list[dict[str, Any]], prevalence: float) -> dict[str, Any] | None:
    """决策曲线（docs/09 §3 净获益公式）：NB(t) = tpr·π − fpr·(1−π)·t/(1−t)。

    tpr/fpr 取自各模型 roc_curve 产物（含 thresholds），π 为全量阳性率。
    """
    series = []
    for row in rows:
        roc = row["artifacts"].get("roc_curve")
        if not roc or "thresholds" not in roc:
            continue
        thresholds = np.asarray(roc["thresholds"], dtype=float)
        finite = np.isfinite(thresholds) & (thresholds > 0) & (thresholds < 1.0)
        if finite.sum() < 2:
            continue
        t = thresholds[finite]
        tpr = np.asarray(roc["tpr"], dtype=float)[finite]
        fpr = np.asarray(roc["fpr"], dtype=float)[finite]
        nb = tpr * prevalence - fpr * (1 - prevalence) * t / (1 - t)
        t_list, nb_list = _thin(t.tolist(), [nb.tolist()])
        series.append(
            {"model_key": row["model_key"], "thresholds": t_list, "net_benefit": nb_list[0]}
        )
    if not series:
        return None
    grid = np.linspace(0.01, 0.99, 50)
    treat_all = (prevalence - (1 - prevalence) * grid / (1 - grid)).tolist()
    return {
        "kind": _DCA,
        "title": "决策曲线（净获益）",
        "data": {
            "series": series,
            "treat_all": {"thresholds": grid.tolist(), "net_benefit": treat_all},
            "prevalence": prevalence,
        },
        "image_uri": None,
    }


def _confusion_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    models = [
        {"model_key": row["model_key"], **row["artifacts"]["confusion_matrix"]}
        for row in rows
        if row["artifacts"].get("confusion_matrix")
    ]
    if not models:
        return None
    return {
        "kind": _CONFUSION,
        "title": "混淆矩阵（阈值 0.5）",
        "data": {"models": models},
        "image_uri": None,
    }


def _km_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """KM 曲线：总体基线 + 各风险模型按中位风险分层（docs/09 §3）。"""
    series = []
    for row in rows:
        km = row["artifacts"].get("km_curve")
        if km:
            times, surv = _thin(list(km["times"]), [list(km["survival"])])
            series.append(
                {
                    "model_key": row["model_key"],
                    "group": "总体",
                    "times": times,
                    "survival": surv[0],
                    "ci_lower": km.get("ci_lower"),
                    "ci_upper": km.get("ci_upper"),
                }
            )
        for group in row["artifacts"].get("km_by_risk", {}).get("groups", []):
            times, surv = _thin(list(group["times"]), [list(group["survival"])])
            series.append(
                {
                    "model_key": row["model_key"],
                    "group": group["name"],
                    "times": times,
                    "survival": surv[0],
                }
            )
    if not series:
        return None
    return {
        "kind": _KM,
        "title": "Kaplan-Meier 曲线（按风险分层）",
        "data": {"series": series},
        "image_uri": None,
    }


def _cindex_forest_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    forest = []
    for row in rows:
        c = (row["metrics"] or {}).get("c_index")
        if not c:
            continue
        forest.append(
            {
                "model_key": row["model_key"],
                "c_index": c["mean"],
                "ci_lower": max(0.0, c["mean"] - 1.96 * c["std"]),
                "ci_upper": min(1.0, c["mean"] + 1.96 * c["std"]),
            }
        )
    if not forest:
        return None
    forest.sort(key=lambda r: r["c_index"], reverse=True)
    return {
        "kind": _CINDEX_FOREST,
        "title": "C-index 森林图（mean ± 1.96·std）",
        "data": {"rows": forest},
        "image_uri": None,
    }


def _hr_forest_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    models = [
        {"model_key": row["model_key"], "rows": row["artifacts"]["hr_forest"]}
        for row in rows
        if row["artifacts"].get("hr_forest")
    ]
    if not models:
        return None
    return {
        "kind": _HR_FOREST,
        "title": "HR 森林图（Cox）",
        "data": {"models": models},
        "image_uri": None,
    }


def _scatter_chart(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    series = []
    for row in rows:
        scatter = row["artifacts"].get("prediction_scatter")
        if not scatter:
            continue
        y_true, ys = _thin(list(scatter["y_true"]), [list(scatter["y_pred"])])
        rmse = (row["metrics"] or {}).get("rmse", {}).get("mean")
        series.append(
            {"model_key": row["model_key"], "y_true": y_true, "y_pred": ys[0], "rmse": rmse}
        )
    if not series:
        return None
    return {
        "kind": _SCATTER,
        "title": "预测值 vs 真实值",
        "data": {"series": series},
        "image_uri": None,
    }


def build_comparison_charts(
    task_type: str,
    rows: list[dict[str, Any]],
    *,
    prevalence: float | None = None,
) -> list[dict[str, Any]]:
    """SUCCESS 模型产物 → ChartAsset 列表（docs/09 §3 图表清单）。

    rows: [{"model_key", "metrics", "artifacts", "explainability"}]；
    prevalence: 分类任务全量阳性率（DCA 必需，由 compare_run 从 target parquet 读取）。
    """
    charts: list[dict[str, Any] | None]
    if task_type == "classification":
        charts = [
            _roc_chart(rows),
            _calibration_chart(rows),
            _dca_chart(rows, prevalence) if prevalence is not None else None,
            _confusion_chart(rows),
            _feature_importance_chart(rows),
        ]
    elif task_type == "survival":
        charts = [
            _km_chart(rows),
            _cindex_forest_chart(rows),
            _hr_forest_chart(rows),
            _feature_importance_chart(rows),
        ]
    else:  # regression
        charts = [_scatter_chart(rows), _feature_importance_chart(rows)]
    return [c for c in charts if c is not None]
