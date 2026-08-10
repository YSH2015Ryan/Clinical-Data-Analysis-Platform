"""ChartAsset JSON → PNG（docs/09 §3 单数据源；docs/10 §3 图表装配）。

报告 PNG 与前端 ECharts 渲染同一份数据 JSON，避免两处不一致。
字体首选 Noto Sans CJK SC（worker/测试镜像已打包 fonts-noto-cjk，
docs/10 §2.1）：特征名等用户原文标签可直接中文渲染；坐标轴/图例
保留英文术语惯例，中文标题由 HTML 模板在 <img> 外呈现。
"""

import base64
import io
from typing import Any

import matplotlib

matplotlib.use("Agg")  # 无显示环境（worker 容器）

import matplotlib.pyplot as plt
import numpy as np

# CJK 字体（docs/10 §2.1）：Noto Sans CJK SC 同时覆盖中英文，单字体即可混排；
# 缺字体环境（本地开发）回退 DejaVu Sans，中文渲染为缺字方块但不中断
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False  # 负号走 ASCII，避免缺字

_KIND_TITLES = {
    "roc": "ROC Curves",
    "calibration": "Calibration Curve",
    "dca": "Decision Curve Analysis",
    "confusion_matrix": "Confusion Matrix (threshold 0.5)",
    "km": "Kaplan-Meier Curves",
    "cindex_forest": "C-index Forest Plot",
    "hr_forest": "Hazard Ratio Forest Plot",
    "feature_importance": "Feature Importance (normalized)",
    "prediction_scatter": "Predicted vs Observed",
}


def _fig_to_png(fig: Any) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _series(data: dict[str, Any]) -> list[dict[str, Any]]:
    return list(data.get("series") or [])


def _line_charts(kind: str, data: dict[str, Any]) -> bytes | None:
    fig, ax = plt.subplots(figsize=(6, 4))
    for s in _series(data):
        if kind == "roc":
            label = f"{s['model_key']} (AUC={s.get('auc'):.3f})" if s.get("auc") else s["model_key"]
            ax.plot(s["fpr"], s["tpr"], label=label)
        elif kind == "calibration":
            ax.plot(s["prob_pred"], s["prob_true"], marker="o", label=str(s["model_key"]))
        elif kind == "dca":
            ax.plot(s["thresholds"], s["net_benefit"], label=str(s["model_key"]))
        elif kind == "km":
            ax.step(s["times"], s["survival"], where="post", label=f"{s['model_key']}/{s['group']}")
    if kind == "roc":
        ax.plot([0, 1], [0, 1], "--", color="gray", label="chance")
        ax.set_xlabel("FPR")
        ax.set_ylabel("TPR")
    elif kind == "calibration":
        ax.plot([0, 1], [0, 1], "--", color="gray", label="ideal")
        ax.set_xlabel("Predicted probability")
        ax.set_ylabel("Observed frequency")
    elif kind == "dca":
        treat_all = data.get("treat_all") or {}
        if treat_all:
            ax.plot(
                treat_all["thresholds"],
                treat_all["net_benefit"],
                "--",
                color="gray",
                label="treat all",
            )
        ax.axhline(0, color="black", linewidth=0.8, linestyle=":", label="treat none")
        ax.set_xlabel("Threshold probability")
        ax.set_ylabel("Net benefit")
    elif kind == "km":
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Time")
        ax.set_ylabel("Survival probability")
    ax.set_title(_KIND_TITLES[kind])
    ax.legend(fontsize=8)
    return _fig_to_png(fig)


def _confusion(data: dict[str, Any]) -> bytes | None:
    models = list(data.get("models") or [])
    if not models:
        return None
    fig, axes = plt.subplots(1, len(models), figsize=(4 * len(models), 3.6))
    if len(models) == 1:
        axes = [axes]
    for ax, m in zip(axes, models, strict=True):
        matrix = np.asarray(m["matrix"], dtype=float)
        labels = [str(x) for x in m.get("labels", [0, 1])]
        im = ax.imshow(matrix, cmap="Blues")
        for (i, j), v in np.ndenumerate(matrix):
            ax.text(j, i, f"{int(v)}", ha="center", va="center")
        ax.set_xticks(range(len(labels)), labels)
        ax.set_yticks(range(len(labels)), labels)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title(str(m["model_key"]))
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle(_KIND_TITLES["confusion_matrix"])
    return _fig_to_png(fig)


def _forest_rows(
    categories: list[str],
    lows: list[float],
    highs: list[float],
    points: list[float],
    x_label: str,
    log_scale: bool,
    title: str,
) -> bytes:
    fig, ax = plt.subplots(figsize=(6, max(2.5, 0.45 * len(categories) + 1)))
    y = np.arange(len(categories))
    ax.errorbar(
        points,
        y,
        xerr=[np.asarray(points) - np.asarray(lows), np.asarray(highs) - np.asarray(points)],
        fmt="o",
        capsize=4,
    )
    if log_scale:
        ax.set_xscale("log")
        ax.axvline(1.0, color="gray", linestyle="--", label="HR=1")
        ax.legend(fontsize=8)
    ax.set_yticks(y, categories)
    ax.invert_yaxis()
    ax.set_xlabel(x_label)
    ax.set_title(title)
    return _fig_to_png(fig)


def _cindex_forest(data: dict[str, Any]) -> bytes | None:
    rows = list(data.get("rows") or [])
    if not rows:
        return None
    return _forest_rows(
        [str(r["model_key"]) for r in rows],
        [float(r["ci_lower"]) for r in rows],
        [float(r["ci_upper"]) for r in rows],
        [float(r["c_index"]) for r in rows],
        "C-index",
        False,
        _KIND_TITLES["cindex_forest"],
    )


def _hr_forest(data: dict[str, Any]) -> bytes | None:
    models = list(data.get("models") or [])
    if not models:
        return None
    figs = []
    for m in models:
        rows = list(m.get("rows") or [])
        if not rows:
            continue
        png = _forest_rows(
            [str(r["feature"]) for r in rows],
            [float(r["ci_lower"]) for r in rows],
            [float(r["ci_upper"]) for r in rows],
            [float(r["hr"]) for r in rows],
            "Hazard Ratio (log scale)",
            True,
            f"{_KIND_TITLES['hr_forest']} — {m['model_key']}",
        )
        figs.append(png)
    return figs[0] if figs else None  # 多模型时取首个（报告按模型拆分由模板迭代）


def _feature_importance(data: dict[str, Any]) -> bytes | None:
    features = [str(f) for f in data.get("features") or []]
    series = _series(data)
    if not features or not series:
        return None
    fig, ax = plt.subplots(figsize=(6, max(3, 0.5 * len(features) + 1)))
    width = 0.8 / len(series)
    y = np.arange(len(features))
    for i, s in enumerate(series):
        ax.barh(y + i * width, s["values"], height=width, label=str(s["model_key"]))
    ax.set_yticks(y + width * (len(series) - 1) / 2, features)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("Normalized importance")
    ax.set_title(_KIND_TITLES["feature_importance"])
    ax.legend(fontsize=8)
    return _fig_to_png(fig)


def _scatter(data: dict[str, Any]) -> bytes | None:
    series = _series(data)
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(5.5, 5))
    all_vals: list[float] = []
    for s in series:
        y_true, y_pred = s["y_true"], s["y_pred"]
        all_vals.extend(y_true)
        all_vals.extend(y_pred)
        label = f"{s['model_key']} (RMSE={s.get('rmse'):.3f})" if s.get("rmse") else s["model_key"]
        ax.scatter(y_true, y_pred, s=12, alpha=0.7, label=label)
    lo, hi = min(all_vals), max(all_vals)
    ax.plot([lo, hi], [lo, hi], "--", color="gray", label="ideal")
    ax.set_xlabel("Observed")
    ax.set_ylabel("Predicted")
    ax.set_title(_KIND_TITLES["prediction_scatter"])
    ax.legend(fontsize=8)
    return _fig_to_png(fig)


def chart_to_png(chart: dict[str, Any]) -> bytes | None:
    """ChartAsset → PNG 字节；未知 kind 或无数据 → None（模板降级为占位文本）。"""
    kind = chart.get("kind")
    data = chart.get("data") or {}
    try:
        if kind in ("roc", "calibration", "dca", "km"):
            if not _series(data):
                return None
            return _line_charts(kind, data)
        if kind == "confusion_matrix":
            return _confusion(data)
        if kind == "cindex_forest":
            return _cindex_forest(data)
        if kind == "hr_forest":
            return _hr_forest(data)
        if kind == "feature_importance":
            return _feature_importance(data)
        if kind == "prediction_scatter":
            return _scatter(data)
    except Exception:
        return None  # 单图失败不阻断报告（docs/10 §5 缺数据显示不适用）
    return None


def chart_to_b64(chart: dict[str, Any]) -> str | None:
    png = chart_to_png(chart)
    return base64.b64encode(png).decode() if png else None
