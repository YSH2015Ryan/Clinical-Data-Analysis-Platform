"""数据缺口建议引擎(路线图 T6.14;红线 8:数值全部真实计算,禁止编造)。

输入:auto_dataset_insight 已产出的确定性事实(eda.sample_size / column_profiles /
research_profile);输出五类缺口建议,每条附 basis 依据串(真实数值 + 公式,可展开核对)。
判断与计算全部确定性规则;LLM 仅后续做表达润色(facts-only),本模块不调用 LLM。

五类缺口(逐项落地,骨架按规则函数注册表扩展):
① EPV 不足(Peduzzi 1996:每变量事件数 ≥10):缺口事件=⌈10×特征数−阳性数⌉,
   需补样本量=⌈缺口事件/阳性率⌉;阳性率=0 时折算无意义,不出数字,改提示确认结局定义。
②–⑤ 待后续子项落地(类别不均衡/生存事件不足/变量角色缺失/组间把握度)。
"""

import math
from typing import Any

# Peduzzi 1996:logistic 模型每变量事件数(events per variable)≥10
EPV_MIN = 10.0


def advise_supplements(
    df: Any,
    eda: dict[str, Any] | None,
    column_profiles: list[dict[str, Any]] | None,
    research_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """计算数据缺口建议。df 保留给后续需要列级数据的规则(④⑤),① 仅用 eda 聚合值。"""
    items: list[dict[str, Any]] = []
    for rule in (_rule_epv_deficit,):
        item = rule(df, eda, column_profiles, research_profile)
        if item is not None:
            items.append(item)
    overall = (
        "当前数据规模满足基本要求,未发现确定性规则可判定的数据缺口。"
        if not items
        else f"发现 {len(items)} 项数据缺口,按下列建议补充数据可提升分析可靠性。"
    )
    return {"items": items, "overall": overall}


def _rule_epv_deficit(
    df: Any,
    eda: dict[str, Any] | None,
    column_profiles: list[dict[str, Any]] | None,
    research_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """① EPV 不足:缺口事件=⌈10×特征数−阳性数⌉,需补样本量=⌈缺口事件/阳性率⌉。

    不适用即不报:无二值结局列(epv is None)或 EPV≥10。
    注:eda._sample_size 的 epv_adequate 仅取 True/None(不足时为 None),
    判定直接以 epv<EPV_MIN 为准,不依赖该标志。
    """
    sample_size = (eda or {}).get("sample_size") or {}
    n_events = sample_size.get("n_events")
    epv = sample_size.get("epv")
    if n_events is None or epv is None or epv >= EPV_MIN:
        return None

    n_rows = sample_size.get("n_rows") or 0
    n_features = sample_size.get("n_features") or 0
    missing_events = max(0, math.ceil(EPV_MIN * n_features - n_events))
    prevalence = n_events / n_rows if n_rows else 0.0

    if prevalence > 0:
        additional_rows: int | None = math.ceil(missing_events / prevalence)
        suggestion = (
            f"按当前阳性率({n_events}/{n_rows}),约需再补充 {additional_rows} 例样本,"
            f"使阳性事件数达到 {int(EPV_MIN * n_features)} 以上(EPV≥10)。"
        )
        basis = (
            f"EPV=阳性事件数/特征数={n_events}/{n_features}={epv}<10(Peduzzi 1996);"
            f"缺口事件=⌈10×{n_features}−{n_events}⌉={missing_events};"
            f"阳性率={n_events}/{n_rows};"
            f"需补样本量=⌈{missing_events}/({n_events}/{n_rows})⌉={additional_rows}"
        )
    else:
        # 阳性率=0:折算样本量在数学上无意义,出数字即编造——改提示确认结局定义
        additional_rows = None
        suggestion = (
            "当前结局列无任何阳性事件,无法折算所需样本量;"
            "请先确认结局定义是否正确(结局列取值是否编码反了或筛选条件过严)。"
        )
        basis = (
            f"EPV=阳性事件数/特征数={n_events}/{n_features}={epv}<10(Peduzzi 1996);"
            f"缺口事件=⌈10×{n_features}−{n_events}⌉={missing_events};"
            f"阳性率={n_events}/{n_rows}=0,折算样本量无意义,不出数字"
        )

    return {
        "deficit_type": "epv",
        "current": {
            "n_rows": n_rows,
            "n_features": n_features,
            "n_events": n_events,
            "epv": epv,
        },
        "target": {"epv_min": int(EPV_MIN), "target_events": int(EPV_MIN * n_features)},
        "gap": {"missing_events": missing_events, "additional_rows": additional_rows},
        "suggestion": suggestion,
        "basis": basis,
    }
