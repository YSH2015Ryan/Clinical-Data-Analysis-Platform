"""动态局限性清单（P3；docs/10 §2 第 9 章局限性）。

静态基础条目（回顾性/单中心/无外部验证/小样本方差）恒在；
动态条目由 payload 真实统计触发（阳性率、EPV、事件数、样本量、
自动修复动作、列缺失率），不虚构任何数值（CLAUDE.md §8）。
"""

from typing import Any

STATIC_LIMITATIONS: list[str] = [
    "本分析基于回顾性数据，可能存在选择偏倚与信息偏倚。",
    "数据来自单中心，结论外推到其他人群需谨慎。",
    "模型未进行外部验证，泛化性能未知。",
    "样本量有限时，交叉验证估计的方差可能较大。",
]

_IMBALANCE_LO, _IMBALANCE_HI = 0.1, 0.9  # 阳性率超出该区间提示类别不均衡
_EPV_MIN = 10.0  # 每变量事件数经验阈值（Peduzzi 1996）
_SURVIVAL_EVENTS_MIN = 100  # 生存任务事件数经验下限
_SMALL_SAMPLE = 200  # 小样本提示阈值
_MISSING_RATE_HIGH = 0.2  # 与校验 missing_warn 阈值同源（docs/05）

# T6.14：体检 supplement_plan 中这些类型已由上方运行级动态条目覆盖
# （运行级口径=建模数据，更贴近报告对象），不重复列入；
# variable_roles/power 无运行级对应条目，并入清单。
_PLAN_TYPES_COVERED_BY_RUN = {"epv", "imbalance", "survival_events"}


def _dynamic_items(payload: dict[str, Any]) -> list[str]:
    items: list[str] = []
    task_type = str((payload.get("run") or {}).get("task_type") or "")
    summary = payload.get("target_summary") or {}
    n_samples = summary.get("n_samples")
    n_features = summary.get("n_features")

    prevalence = summary.get("prevalence")
    if prevalence is not None and (prevalence < _IMBALANCE_LO or prevalence > _IMBALANCE_HI):
        items.append(
            f"结局类别不均衡（阳性率 {prevalence * 100:.1f}%）：阈值 0.5 下的混淆矩阵解读需谨慎，"
            "建议以 PR 曲线与校准度为主要评估依据。"
        )

    # EPV：分类=阳性数/变量数；生存=事件数/变量数
    events = summary.get("positives") if task_type == "classification" else summary.get("events")
    if events is not None and n_features:
        epv = events / n_features
        if epv < _EPV_MIN:
            items.append(
                f"每变量事件数（EPV）约为 {epv:.1f}，低于经验阈值 {int(_EPV_MIN)}，"
                "系数估计可能不稳定，建议减少入模变量或采用正则化模型。"
            )

    if task_type == "survival":
        n_events = summary.get("events")
        if n_events is not None and n_events < _SURVIVAL_EVENTS_MIN:
            items.append(
                f"生存事件数仅 {n_events} 例（<{_SURVIVAL_EVENTS_MIN}），"
                "模型自由度受限，过拟合风险较高。"
            )

    if n_samples is not None and n_samples < _SMALL_SAMPLE:
        items.append(
            f"样本量较小（N={n_samples}），交叉验证折间波动可能掩盖真实的模型间差异。"
        )

    transform_log = payload.get("transform_log") or []
    if transform_log:
        items.append(
            f"建模数据经 {len(transform_log)} 项自动修复处理（详见第 2 章数据处理动作），"
            "修复引入的偏移需在论文方法学部分如实披露。"
        )

    profiles = ((payload.get("quality_report") or {}).get("column_profiles")) or []
    high_missing = [
        (str(p.get("name")), float(p.get("missing_rate") or 0.0))
        for p in profiles
        if float(p.get("missing_rate") or 0.0) > _MISSING_RATE_HIGH
    ]
    for name, rate in high_missing[:3]:  # 最多列 3 个，避免清单冗长
        items.append(
            f"变量 {name} 缺失率 {rate * 100:.1f}%，其分析结果对缺失机制假设较敏感。"
        )

    # T6.14：体检缺口建议(同一事实源 DatasetInsight.payload.supplement_plan)
    plan = payload.get("supplement_plan") or {}
    for plan_item in plan.get("items") or []:
        if plan_item.get("deficit_type") in _PLAN_TYPES_COVERED_BY_RUN:
            continue
        suggestion = plan_item.get("suggestion")
        if suggestion:
            items.append(f"数据缺口（体检）：{suggestion}")
    return items


def build_limitations(payload: dict[str, Any]) -> list[str]:
    """动态条目在前（本次数据特有），静态基础条目在后（研究设计共性）。"""
    return [*_dynamic_items(payload), *STATIC_LIMITATIONS]
