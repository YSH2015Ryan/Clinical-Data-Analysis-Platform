"""Analysis Status 状态灯（updateplan §69 / P0-10）。

GREEN / YELLOW / RED 由确定性规则系统判定，不由 LLM 决定：
- RED：重大数据或方法学问题——完整性门禁阻断项、critical 级泄漏
  （如日期重建目标）、完美指标红旗、数据质量 critical（RV502 类）、
  EPV<5（§19 critical 档）。
- YELLOW：分析完成但有重要局限——泄漏 warning、质量 warning、
  5≤EPV<10（§19 warning 档）。
- GREEN：以上均无，适合解读。

§70：RED 时报告首页必须以醒目横幅展示固定 Scope of Use 声明
（固定文案，非 LLM 生成，不得改写）。
"""

from typing import Any

from app.engines.reporting.redflags import detect_perfect_metric_redflag

# updateplan §70 固定声明文本（ verbatim，不得改写 / 非 LLM 生成）
SCOPE_OF_USE = (
    "This tool is designed to support early-stage clinical research "
    "data exploration and methodological screening. "
    "It does NOT constitute medical advice, a clinical decision-support "
    "system, or a substitute for consultation with a qualified "
    "biostatistician, epidemiologist, or the study's IRB/ethics committee. "
    "Results, especially those generated under Exploratory Mode or under "
    "a RED analysis status, must not be used to guide patient care or be "
    "presented as confirmatory findings without independent statistical review."
)

_STATUS_LABELS = {
    "GREEN": "分析适合解读",
    "YELLOW": "分析已完成，但存在重要局限",
    "RED": "检测到重大数据或方法学问题",
}

# updateplan §72 固定声明（verbatim，非 LLM 生成，不得改写）：
# 探索性模式下报告必须声明结果不得按无偏预测性能解读
EXPLORATORY_STATEMENT = (
    "Results should not be interpreted as unbiased predictive performance."
)


def _epv(payload: dict[str, Any]) -> float | None:
    summary = payload.get("target_summary") or {}
    n_features = summary.get("n_features")
    if not n_features:
        return None
    events = summary.get("positives")
    if events is None:
        events = summary.get("events")
    if events is None:
        return None
    return float(events) / float(n_features)


def compute_analysis_status(payload: dict[str, Any]) -> dict[str, Any]:
    """按确定性规则计算状态灯；返回 level/label/reasons/scope_banner。"""
    red: list[str] = []
    yellow: list[str] = []

    findings = (payload.get("integrity") or {}).get("findings") or []
    for f in findings:
        if not isinstance(f, dict):
            continue
        code = str(f.get("code") or "")
        if f.get("severity") == "blocker":
            red.append(f"完整性门禁阻断项：{code}")
        elif f.get("severity") == "critical":
            red.append(f"重大泄漏风险：{code}")
        elif f.get("severity") == "warning":
            yellow.append(f"泄漏/分组警示：{code}")

    quality = payload.get("quality") or {}
    if quality.get("criticals"):
        red.append(f"数据质量严重问题 {quality['criticals']} 项（须人工复核后方可采信）")
    if quality.get("warnings"):
        yellow.append(f"数据质量警告 {quality['warnings']} 项")

    red_flag = detect_perfect_metric_redflag(payload)
    if red_flag is not None:
        red.append("完美指标红旗：接近满分的性能叠加低 EPV，疑似过拟合/数据泄漏")

    epv = _epv(payload)
    if epv is not None:
        if epv < 5:
            red.append(f"EPV={epv:.1f}<5：每变量事件数严重不足，性能指标易虚高")
        elif epv < 10:
            yellow.append(f"EPV={epv:.1f}（5–10）：候选变量相对事件数偏多，结果按探索性解读")

    if red:
        level = "RED"
    elif yellow:
        level = "YELLOW"
    else:
        level = "GREEN"

    # §72：探索性模式（用户确认在 critical 级方法学问题下继续）强制 RED，
    # 报告必须声明结果不得按无偏预测性能解读
    exploratory = bool((payload.get("run") or {}).get("exploratory_mode"))
    if exploratory:
        level = "RED"
        red.insert(0, "探索性分析模式：用户确认在存在 critical 级方法学问题的情况下继续（§72）")

    return {
        "level": level,
        "label": _STATUS_LABELS[level],
        "reasons": red if level == "RED" else yellow,
        # §70：RED 时首页醒目横幅展示固定 Scope of Use 声明
        "scope_banner": level == "RED",
        "scope_of_use": SCOPE_OF_USE,
        # §72：探索性模式固定声明（非探索性 → None → 模板不渲染）
        "exploratory_statement": EXPLORATORY_STATEMENT if exploratory else None,
    }
