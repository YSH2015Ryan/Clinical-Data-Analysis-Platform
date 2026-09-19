"""研究机会与假设生成（P2-06 + updateplan §81；红线 8：数值全部来自体检真实计算）。

从阶段 A 体检事实（EDA 相关对/样本量/缺失/不均衡、列画像、研究画像、缺口建议）
确定性生成五类研究机会：

```text
Observed Patterns           观察到的模式（强相关、不均衡、高缺失）
Unexpected Associations     意外关联（|r|≥0.7 强相关对，需核实同源测量/泄漏）
Potential Subgroup Differences  潜在亚组差异（2-6 水平分类列候选）
Potential Prediction Tasks  潜在预测任务（由研究画像推导）
Potential Hypotheses        潜在可检验假设（模板化，引用真实数值）
```

Principle 6 纪律：全部条目标记 Hypothesis-generating，固定声明探索性≠确认性；
禁止「Novel Finding / Guaranteed Publishable」类措辞。规则保底，不调用 LLM
（与 insight 阶段约定一致；llm_summary 槽位预留，接线时走 services/llm_tasks
幻觉校验）。
"""

from typing import Any

import pandas as pd

_NOTICE = (
    "以下内容为 Hypothesis-generating（假设生成）性质：所有条目由确定性规则从本数据集的"
    "真实统计事实推导，仅供形成研究假设参考；探索性发现不等于确认性结论，"
    "任何假设须在独立数据集上验证后方可写入论文结论。"
)

_STRONG_R = 0.5  # 观察到的模式：|r| 下限
_SURPRISE_R = 0.7  # 意外关联：|r| 下限（需核实同源测量/泄漏）
_TOP_N = 5  # 各类清单上限
_SUBGROUP_MIN_LVL, _SUBGROUP_MAX_LVL = 2, 6  # 亚组变量水平数窗口
_HIGH_MISSING = 0.2  # 高缺失列阈值（同 docs/05 missing_warn）
_IMBALANCE_LO, _IMBALANCE_HI = 0.1, 0.9  # 不均衡区间（同 limitations）

# 结局/分组语义列不作为亚组候选
_EXCLUDE_SEMANTICS = {"Event", "Label", "FollowUp"}

_RESEARCH_TYPE_ZH = {
    "cohort": "队列研究",
    "case_control": "病例对照研究",
    "cross_sectional": "横断面研究",
    "time_series": "时间序列研究",
}


def _item(text: str, basis: str) -> dict[str, Any]:
    return {"text": text, "basis": basis}


def _observed_patterns(eda: dict[str, Any], profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    top_pairs = (((eda.get("correlations") or {}).get("continuous")) or {}).get("top_pairs") or []
    for p in top_pairs:
        if abs(float(p["r"])) >= _STRONG_R:
            items.append(
                _item(
                    f"「{p['a']}」与「{p['b']}」呈强线性相关（Pearson r={p['r']:.2f}）。",
                    f"eda.correlations.top_pairs 真实值：{p['a']}~{p['b']} r={p['r']}"
                    f"（|r|≥{_STRONG_R} 阈值）",
                )
            )
    sample = eda.get("sample_size") or {}
    prevalence = sample.get("prevalence")
    if prevalence is not None and (prevalence < _IMBALANCE_LO or prevalence > _IMBALANCE_HI):
        items.append(
            _item(
                f"结局类别不均衡（阳性率 {prevalence * 100:.1f}%）。",
                f"eda.sample_size.prevalence={prevalence}（真实值），"
                f"超出 [{_IMBALANCE_LO}, {_IMBALANCE_HI}] 区间",
            )
        )
    high_missing = [
        (str(p.get("name")), float(p.get("missing_rate") or 0.0))
        for p in profiles
        if float(p.get("missing_rate") or 0.0) > _HIGH_MISSING
    ]
    for name, rate in high_missing[:3]:
        items.append(
            _item(
                f"「{name}」缺失率较高（{rate * 100:.1f}%），其分布观察需谨慎。",
                f"column_profiles：{name} missing_rate={rate}（真实值）>{_HIGH_MISSING}",
            )
        )
    return items[:_TOP_N]


def _unexpected_associations(eda: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    top_pairs = (((eda.get("correlations") or {}).get("continuous")) or {}).get("top_pairs") or []
    for p in top_pairs:
        if abs(float(p["r"])) >= _SURPRISE_R:
            items.append(
                _item(
                    f"「{p['a']}」与「{p['b']}」相关性强到异常（r={p['r']:.2f}）："
                    "需核实是否同源测量、派生变量或录入伪迹；若为独立测量，"
                    "该关联本身值得作为研究线索。",
                    f"eda.correlations.top_pairs 真实值：r={p['r']}（|r|≥{_SURPRISE_R} 阈值）",
                )
            )
    return items[:3]


def _subgroup_candidates(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in profiles:
        if p.get("inferred_type") != "categorical":
            continue
        if p.get("semantic") in _EXCLUDE_SEMANTICS:
            continue
        unique = p.get("unique")
        if unique is None or not (_SUBGROUP_MIN_LVL <= int(unique) <= _SUBGROUP_MAX_LVL):
            continue
        items.append(
            {
                "variable": str(p.get("name")),
                "text": f"「{p.get('name')}」（{int(unique)} 个水平）可作为亚组变量，"
                "检验暴露-结局关联是否存在效应修饰。",
                "basis": f"column_profiles：{p.get('name')} inferred_type=categorical，"
                f"unique={unique}（{int(unique)}∈[{_SUBGROUP_MIN_LVL},{_SUBGROUP_MAX_LVL}] 真实值）",
            }
        )
    return items[:_TOP_N]


def _prediction_tasks(
    research_profile: dict[str, Any] | None,
    sample: dict[str, Any],
) -> list[dict[str, Any]]:
    profile = research_profile or {}
    research_type = str(profile.get("research_type") or "")
    models = profile.get("recommended_models") or []
    if not research_type:
        return []
    type_zh = _RESEARCH_TYPE_ZH.get(research_type, research_type)
    items = [
        _item(
            f"按{type_zh}设计，可构建结局预测模型（候选：{'、'.join(models) or '见画像'}）。",
            f"research_profile.research_type={research_type}，"
            f"recommended_models={models}（画像真实输出）",
        )
    ]
    n_events = sample.get("n_events")
    if n_events is not None:
        items.append(
            _item(
                f"以事件发生为结局的风险分层任务（当前事件数 {n_events} 例）。",
                f"eda.sample_size.n_events={n_events}（真实值）",
            )
        )
    return items


def _hypotheses(
    eda: dict[str, Any],
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """模板化可检验假设：强相关对 + 不均衡/缺失事实，全部引用真实数值。"""
    items: list[dict[str, Any]] = []
    top_pairs = (((eda.get("correlations") or {}).get("continuous")) or {}).get("top_pairs") or []
    for p in top_pairs[:2]:
        if abs(float(p["r"])) >= _STRONG_R:
            items.append(
                _item(
                    f"假设（待检验）：「{p['a']}」与「{p['b']}」的关联（本数据 r={p['r']:.2f}）"
                    "在独立数据集中仍然成立，且不被共同原因（如年龄/病情严重程度）完全解释。",
                    f"源自 eda.correlations 真实相关值 r={p['r']}；"
                    "验证路径：独立队列重测 + 混杂校正关联分析",
                )
            )
    sample = eda.get("sample_size") or {}
    prevalence = sample.get("prevalence")
    if prevalence is not None and (prevalence < _IMBALANCE_LO or prevalence > _IMBALANCE_HI):
        items.append(
            _item(
                f"假设（待检验）：少数类亚群（占比 {min(prevalence, 1 - prevalence) * 100:.1f}%）"
                "具有与多数类不同的特征谱，值得单独刻画。",
                f"源自 eda.sample_size.prevalence={prevalence}（真实值）；"
                "验证路径：按结局分层的基线特征表（Table 1）+ 亚组分析",
            )
        )
    return items[:3]


def generate_research_opportunities(
    df: Any,
    eda: dict[str, Any] | None,
    column_profiles: list[dict[str, Any]] | None,
    research_profile: dict[str, Any] | None,
    supplement_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成五类研究机会（§81）。df 保留给后续需要行级数据的规则；当前全部用聚合事实。"""
    eda = eda or {}
    profiles = [p for p in (column_profiles or []) if isinstance(p, dict)]
    return {
        "hypothesis_generating": True,
        "notice": _NOTICE,
        "observed_patterns": _observed_patterns(eda, profiles),
        "unexpected_associations": _unexpected_associations(eda),
        "potential_subgroup_differences": _subgroup_candidates(profiles),
        "potential_prediction_tasks": _prediction_tasks(research_profile, eda.get("sample_size") or {}),
        "potential_hypotheses": _hypotheses(eda, profiles),
        # LLM 表达增强槽位（规则保底；接线时由 services/llm_tasks 幻觉校验兜底）
        "llm_summary": None,
    }
