"""完美指标红旗（T6.15②，科学诚实 P0；docs/10 §2 增补规范）。

触发规则（双条件缺一不可）：EPV<10（Peduzzi 1996 经验阈值）且主指标
交叉验证均值 ≥0.99。教科书上接近满分的指标在小 EPV 数据上几乎必然
源于过拟合或数据泄漏，报告必须醒目警示而非照常推荐（红线 8：科学诚实
优先于表达美观）。

红旗只改措辞与新增警示段落，不改排名数值；所有引用数值（EPV/指标/
特征名）均来自 payload 真实计算，不做因果断言。
"""

from typing import Any

RED_FLAG_EPV_MAX = 10.0  # EPV 低于该值才谈得上「小样本过拟合」语境
RED_FLAG_METRIC_MIN = 0.99  # 主指标均值达到该值视为「过于完美」


def _top1_metric_mean(payload: dict[str, Any]) -> tuple[str | None, float | None, str | None]:
    """从 comparison/table 取 Top1 模型的主指标交叉验证均值（真实值，缺则 None）。"""
    comparison = payload.get("comparison") or {}
    recommendation = comparison.get("recommendation") or {}
    primary = recommendation.get("primary_metric")
    ranking = comparison.get("ranking") or []
    table = payload.get("table") or []
    if not primary or not ranking or not table:
        return None, None, None
    top_key = ranking[0]
    for row in table:
        if row.get("model_key") == top_key:
            mean = ((row.get("metrics") or {}).get(primary) or {}).get("mean")
            return str(primary), (float(mean) if mean is not None else None), str(top_key)
    return str(primary), None, str(top_key)


def _top1_feature(payload: dict[str, Any]) -> str | None:
    """Top1 重要性特征名（feature_importance 图真实数据；无图 → None）。"""
    for chart in (payload.get("comparison") or {}).get("charts") or []:
        if chart.get("kind") == "feature_importance":
            features = (chart.get("data") or {}).get("features") or []
            if features:
                return str(features[0])
    return None


def detect_perfect_metric_redflag(payload: dict[str, Any]) -> dict[str, Any] | None:
    """检测完美指标红旗；不触发返回 None，触发返回真实数值与警示文案。

    返回键：epv / metric / metric_value / model_key / top_feature /
    limitation（局限性条目）/ warning（结论章警示段）。
    """
    integrity = payload.get("integrity") or {}
    findings = integrity.get("findings") or []
    if any(f.get("severity") == "blocker" for f in findings if isinstance(f, dict)):
        return {
            "integrity_blocked": True,
            "warning": (
                "Critical methodological review required. "
                "分析完整性门禁发现阻断级问题，禁止将模型性能解释为可信临床效能。"
            ),
            "findings": findings,
        }

    task_type = (payload.get("run") or {}).get("task_type")
    if task_type not in ("classification", "survival"):
        return None

    summary = payload.get("target_summary") or {}
    n_features = summary.get("n_features")
    events = summary.get("positives") if task_type == "classification" else summary.get("events")
    if events is None or not n_features:
        return None
    epv = events / n_features
    if epv >= RED_FLAG_EPV_MAX:
        return None

    metric, metric_value, model_key = _top1_metric_mean(payload)
    if metric is None or metric_value is None or metric_value < RED_FLAG_METRIC_MIN:
        return None

    top_feature = _top1_feature(payload)
    feature_hint = (
        f"重要性排名第一的特征为「{top_feature}」，请优先核查其是否为结局的代理变量"
        "（如结局的直接记录、治疗后指标或数据录入伪迹）；"
        if top_feature
        else ""
    )
    limitation = (
        f"每变量事件数（EPV）仅 {epv:.1f} 而主指标 {metric} 交叉验证均值高达 "
        f"{metric_value:.4f}：在事件数如此有限的数据上出现接近满分的区分度，"
        "教科书经验指向过拟合/数据泄漏而非真实性能，本报告所有性能指标的解读"
        "须以此为前提。"
    )
    warning = (
        f"结果过于完美，疑似过拟合/数据泄漏：EPV={epv:.1f}（经验阈值 ≥10），"
        f"推荐模型 {model_key} 的 {metric}={metric_value:.4f}。{feature_hint}"
        "下列推荐在上述疑点排除前仅供参考，投稿前必须核查特征-结局因果链与"
        "数据切分流程（泄漏常发生在预处理/切分顺序）。"
    )
    return {
        "epv": round(epv, 4),
        "metric": metric,
        "metric_value": metric_value,
        "model_key": model_key,
        "top_feature": top_feature,
        "limitation": limitation,
        "warning": warning,
    }
