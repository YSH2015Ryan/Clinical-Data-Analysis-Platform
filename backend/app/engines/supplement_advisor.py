"""数据缺口建议引擎(路线图 T6.14;红线 8:数值全部真实计算,禁止编造)。

输入:auto_dataset_insight 已产出的确定性事实(eda.sample_size / column_profiles /
research_profile);输出五类缺口建议,每条附 basis 依据串(真实数值 + 公式,可展开核对)。
判断与计算全部确定性规则;LLM 仅后续做表达润色(facts-only),本模块不调用 LLM。

五类缺口(逐项落地,骨架按规则函数注册表扩展):
① EPV 不足(Peduzzi 1996:每变量事件数 ≥10):缺口事件=⌈10×特征数−阳性数⌉,
   需补样本量=⌈缺口事件/阳性率⌉;阳性率=0 时折算无意义,不出数字,改提示确认结局定义。
② 类别不均衡:少数类占比 <10%(对称判定,阳性率 >90% 同样触发);
   需补少数类=⌈多数类/9⌉−少数类(假设明示:多数类不变、目标占比 10% 为本规则阈值);
   ① 已触发时去重不报(① 的补样数字已覆盖同一缺口)。
③ 生存事件不足:队列研究(随访时间列+0/1 事件列)且事件数<100(本规则经验下限,
   依据串明示);缺口=100−事件数,建议引用真实中位随访时间。
④⑤ 待后续子项落地(变量角色缺失/组间把握度)。
"""

import math
from typing import Any

import pandas as pd

from app.engines.research_profiler import _event_columns, _follow_up_columns

# Peduzzi 1996:logistic 模型每变量事件数(events per variable)≥10
EPV_MIN = 10.0
# 类别不均衡阈值:少数类占比 <10%
IMBALANCE_MINORITY_RATE_MAX = 0.10
# 生存分析事件数经验下限(本规则阈值,非外部金标准)
SURVIVAL_EVENTS_MIN = 100


def advise_supplements(
    df: Any,
    eda: dict[str, Any] | None,
    column_profiles: list[dict[str, Any]] | None,
    research_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """计算数据缺口建议。df 保留给后续需要列级数据的规则(④⑤),①② 仅用 eda 聚合值。"""
    items: list[dict[str, Any]] = []
    epv_item = _rule_epv_deficit(df, eda, column_profiles, research_profile)
    if epv_item is not None:
        items.append(epv_item)
    # ② 与① 去重:① 已触发时其补样数字已覆盖同一缺口,② 不再报
    imbalance_item = _rule_class_imbalance(
        df, eda, column_profiles, research_profile, skip=epv_item is not None
    )
    if imbalance_item is not None:
        items.append(imbalance_item)
    survival_item = _rule_survival_events(df, eda, column_profiles, research_profile)
    if survival_item is not None:
        items.append(survival_item)
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


def _rule_class_imbalance(
    df: Any,
    eda: dict[str, Any] | None,
    column_profiles: list[dict[str, Any]] | None,
    research_profile: dict[str, Any] | None,
    *,
    skip: bool = False,
) -> dict[str, Any] | None:
    """② 类别不均衡:少数类占比 <10%(对称判定)。

    需补少数类=⌈多数类/9⌉−少数类——假设:多数类样本不变,目标占比 10% 为本规则
    阈值本身(依据串明示,非外部金标准)。① 已触发时 skip=True 去重不报。
    不适用即不报:无二值结局列或空表。
    """
    if skip:
        return None
    sample_size = (eda or {}).get("sample_size") or {}
    n_events = sample_size.get("n_events")
    n_rows = sample_size.get("n_rows") or 0
    if n_events is None or n_rows == 0:
        return None

    n_nonevents = n_rows - n_events
    minority = min(n_events, n_nonevents)
    majority = max(n_events, n_nonevents)
    minority_label = "阳性" if n_events <= n_nonevents else "阴性"
    minority_rate = minority / n_rows
    if minority_rate >= IMBALANCE_MINORITY_RATE_MAX:
        return None

    # 目标:m/(m+多数类)=0.10 → m=多数类/9
    additional = max(0, math.ceil(majority / 9) - minority)
    prevalence = round(n_events / n_rows, 4)
    suggestion = (
        f"少数类({minority_label})占比仅 {round(minority_rate, 4)}"
        f"({minority}/{n_rows}),建模时类别权重、分层抽样与阈值校准必不可少,"
        f"评估应以 PR-AUC/灵敏度/特异度为主而非 accuracy;"
        f"若希望不新增多数类而将少数类占比提升至 10%,约需再补充 {additional} 例"
        f"{minority_label}样本。"
    )
    basis = (
        f"少数类({minority_label})={minority},多数类={majority};"
        f"少数类占比={n_events}/{n_rows}={prevalence}(阳性口径)不对称时取 min,"
        f"实际少数类占比={minority}/{n_rows}={round(minority_rate, 4)}<0.10;"
        f"需补少数类=⌈{majority}/9⌉−{minority}={additional}"
        f"(假设:多数类不变,目标占比 10% 为本规则阈值)"
    )
    return {
        "deficit_type": "imbalance",
        "current": {
            "n_rows": n_rows,
            "n_events": n_events,
            "n_nonevents": n_nonevents,
            "prevalence": prevalence,
            "minority_rate": round(minority_rate, 4),
            "minority_label": minority_label,
        },
        "target": {"minority_rate_min": IMBALANCE_MINORITY_RATE_MAX},
        "gap": {"additional_minority_rows": additional},
        "suggestion": suggestion,
        "basis": basis,
    }


def _rule_survival_events(
    df: Any,
    eda: dict[str, Any] | None,
    column_profiles: list[dict[str, Any]] | None,
    research_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """③ 生存事件不足:队列研究且事件数<100(本规则经验下限,依据串明示)。

    结构判定复用 research_profiler 的随访/事件列探测器(同一约定,不重复实现);
    研究类型以研究画像为准(画像为横断面时即使结构相似也不报);事件数/中位随访
    全部从 df 真实计算。无 df/无随访列/无事件列 → 无法判定,不误报。
    """
    if not isinstance(df, pd.DataFrame):
        return None
    if (research_profile or {}).get("research_type") != "cohort":
        return None
    follow_cols = _follow_up_columns(df, {})
    event_cols = _event_columns(df, {})
    if not follow_cols or not event_cols:
        return None

    event_col = event_cols[0]
    follow_col = follow_cols[0]
    n_events = int((pd.to_numeric(df[event_col], errors="coerce") == 1).sum())
    if n_events >= SURVIVAL_EVENTS_MIN:
        return None

    follow_median_raw = pd.to_numeric(df[follow_col], errors="coerce").median()
    follow_median = (
        None if pd.isna(follow_median_raw) else round(float(follow_median_raw), 2)
    )
    missing = SURVIVAL_EVENTS_MIN - n_events
    median_text = (
        f"当前中位随访 {follow_median}({follow_col})," if follow_median is not None else ""
    )
    suggestion = (
        f"生存分析事件数仅 {n_events} 例(列 {event_col}),低于经验下限 "
        f"{SURVIVAL_EVENTS_MIN};{median_text}建议延长随访以累积事件或补充入组,"
        f"约需再积累 {missing} 例事件,否则 Cox/生存模型的回归系数不稳定。"
    )
    basis = (
        f"事件列={event_col},随访列={follow_col};"
        f"事件数={n_events}<{SURVIVAL_EVENTS_MIN}(本规则经验阈值,非外部金标准);"
        f"缺口={SURVIVAL_EVENTS_MIN}−{n_events}={missing};"
        f"中位随访={follow_median if follow_median is not None else '无法计算'}"
    )
    return {
        "deficit_type": "survival_events",
        "current": {
            "n_rows": len(df),
            "n_events": n_events,
            "event_column": event_col,
            "follow_up_column": follow_col,
            "follow_up_median": follow_median,
        },
        "target": {"events_min": SURVIVAL_EVENTS_MIN},
        "gap": {"missing_events": missing},
        "suggestion": suggestion,
        "basis": basis,
    }
