"""科研流程模板库（T6.9）：预后模型/危险因素/剂量反应/纵向 四类研究模板。

每个模板给出：推荐任务类型、模型（注册表 key）、图表（ChartAsset.kind），
并按数据集真实统计（行数/事件数/特征数）核对样本量经验规则
（EPV≥10、n/p≥20、纵向 n≥50），所有数值真实计算，不虚构（红线8）。

分层纪律：engines 只依赖标准库/数据处理库；列检测复用 research_profiler。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.engines import research_profiler as profiler

# 模型注册表内置 key（app.plugins.builtin；契约只承诺注册表内 key）
KNOWN_MODEL_KEYS: frozenset[str] = frozenset(
    {
        "logreg",
        "rf",
        "svm",
        "xgboost",
        "lightgbm",
        "catboost",
        "lasso",
        "elasticnet",
        "rf_reg",
        "xgboost_reg",
        "coxph",
        "rsf",
        "gbs",
        "deepsurv",
        "km",
        "gam",
        "gee",
        "dlnm",
        "poisson",
        "negbin",
        "dummy",
    }
)

# docs/14 ChartAsset.kind 枚举
KNOWN_CHART_KINDS: frozenset[str] = frozenset(
    {
        "roc",
        "calibration",
        "dca",
        "confusion_matrix",
        "km",
        "cindex_forest",
        "hr_forest",
        "feature_importance",
        "prediction_scatter",
    }
)

_EPV_THRESHOLD = 10  # 每变量事件数经验下限（logistic/Cox 通用）
_N_PER_PREDICTOR_THRESHOLD = 20  # 回归每预测因子样本数经验下限
_LONGITUDINAL_MIN_N = 50  # 纵向/重复测量样本量经验下限


@dataclass(frozen=True)
class ResearchTemplate:
    key: str
    name: str
    description: str


TEMPLATES: tuple[ResearchTemplate, ...] = (
    ResearchTemplate(
        key="prognostic_model",
        name="预后模型",
        description=(
            "构建并验证个体结局预测模型（生存结局用 Cox/机器学习，二分类结局用"
            "Logistic/机器学习），报告区分度、校准度与临床净获益，对标 TRIPOD。"
        ),
    ),
    ResearchTemplate(
        key="risk_factor",
        name="危险因素分析",
        description=(
            "识别二分类结局的独立关联因素：Logistic 回归为主给出效应方向与显著性，"
            "机器学习模型作非线性佐证，对标 STROBE。"
        ),
    ),
    ResearchTemplate(
        key="dose_response",
        name="剂量反应关系",
        description=(
            "刻画连续暴露（剂量）与连续结局间的剂量-反应形态：GAM 捕捉非线性，"
            "正则化/树模型作对照，对标 STROBE。"
        ),
    ),
    ResearchTemplate(
        key="longitudinal",
        name="纵向/重复测量",
        description=(
            "分析含时间索引的重复测量数据：GEE 处理个体内相关，GAM 刻画时间趋势，" "树模型作对照。"
        ),
    ),
)


def list_templates() -> list[dict[str, Any]]:
    """模板元信息（不依赖数据集）。"""
    return [
        {
            "key": t.key,
            "name": t.name,
            "description": t.description,
            "models": sorted(_template_models(t.key)),
            "charts": sorted(_template_charts(t.key)),
        }
        for t in TEMPLATES
    ]


def _template_models(key: str, survival: bool = True) -> list[str]:
    if key == "prognostic_model":
        return ["coxph", "rsf", "gbs"] if survival else ["logreg", "rf", "xgboost"]
    if key == "risk_factor":
        return ["logreg", "rf", "xgboost"]
    if key == "dose_response":
        return ["gam", "lasso", "rf_reg"]
    return ["gee", "gam", "rf_reg"]  # longitudinal


def _template_charts(key: str, survival: bool = True) -> list[str]:
    if key == "prognostic_model":
        return (
            ["km", "cindex_forest", "hr_forest", "calibration", "dca", "feature_importance"]
            if survival
            else ["roc", "calibration", "dca", "feature_importance"]
        )
    if key == "risk_factor":
        return ["roc", "calibration", "confusion_matrix", "feature_importance"]
    return ["prediction_scatter", "feature_importance"]  # dose_response / longitudinal


def _advice(
    rule: str, value: float | None, threshold: float, meets: bool, text: str
) -> dict[str, Any]:
    return {"rule": rule, "value": value, "threshold": threshold, "meets": meets, "text": text}


def _epv_advice(events: int | None, n_features: int) -> dict[str, Any]:
    """EPV（每变量事件数）核对：logistic/Cox 经验下限 10。"""
    if events is None or n_features <= 0:
        return _advice(
            "EPV ≥ 10",
            None,
            _EPV_THRESHOLD,
            False,
            "未检测到事件/阳性计数，无法核对每变量事件数（EPV），" "请确认结局列后重新评估。",
        )
    epv = events / n_features
    meets = epv >= _EPV_THRESHOLD
    verdict = "满足" if meets else "低于"
    return _advice(
        "EPV ≥ 10",
        round(epv, 2),
        _EPV_THRESHOLD,
        meets,
        f"事件/阳性数 {events}，候选预测因子 {n_features} 个，EPV = {epv:.1f}，"
        f"{verdict}经验下限 {_EPV_THRESHOLD}（EPV 过低时回归系数不稳定，"
        "建议精简特征或扩大样本）。",
    )


def _n_per_predictor_advice(n_rows: int, n_features: int) -> dict[str, Any]:
    """回归 n/p（每预测因子样本数）核对：经验下限 20。"""
    if n_features <= 0:
        return _advice(
            "n/p ≥ 20",
            None,
            _N_PER_PREDICTOR_THRESHOLD,
            False,
            "未检测到可用预测因子列，无法核对样本量与变量数比例。",
        )
    ratio = n_rows / n_features
    meets = ratio >= _N_PER_PREDICTOR_THRESHOLD
    verdict = "满足" if meets else "低于"
    return _advice(
        "n/p ≥ 20",
        round(ratio, 2),
        _N_PER_PREDICTOR_THRESHOLD,
        meets,
        f"样本量 {n_rows}，候选预测因子 {n_features} 个，n/p = {ratio:.1f}，"
        f"{verdict}经验下限 {_N_PER_PREDICTOR_THRESHOLD}。",
    )


def _longitudinal_n_advice(n_rows: int) -> dict[str, Any]:
    meets = n_rows >= _LONGITUDINAL_MIN_N
    verdict = "满足" if meets else "低于"
    return _advice(
        f"n ≥ {_LONGITUDINAL_MIN_N}",
        n_rows,
        _LONGITUDINAL_MIN_N,
        meets,
        f"记录数 {n_rows}，{verdict}纵向/重复测量分析的经验下限 "
        f"{_LONGITUDINAL_MIN_N}（GEE 大样本性质依赖足够独立个体数）。",
    )


def _minority_count(series: pd.Series) -> int | None:
    """二分类序列的少数类计数（EPV 用；无法判定 → None）。"""
    if not profiler._is_binary(series):
        return None
    codes = pd.Categorical(series).codes
    positives = int((codes == 1).sum())
    return min(positives, int(len(codes) - positives))


def _binary_outcome_column(df: pd.DataFrame, hints: dict[str, Any]) -> str | None:
    """二分类结局列检测：显式 hint → 结局/事件提示词命中 → 任意二分类列兜底。

    不复用 profiler._outcome_column：它把事件列排除在结局之外（服务研究类型
    判定），而模板评估恰恰要把 0/1 事件列当作可选结局。
    """
    explicit = hints.get("outcome") or hints.get("outcome_column") or hints.get("label_col")
    if explicit in df.columns and profiler._is_binary(df[explicit]):
        return str(explicit)
    excluded = set(profiler._time_columns(df) + profiler._follow_up_columns(df, hints))
    hinted = profiler._OUTCOME_HINTS + profiler._EVENT_HINTS
    for col in df.columns:
        name = str(col)
        if (
            name not in excluded
            and profiler._name_has(name, hinted)
            and profiler._is_binary(df[col])
        ):
            return name
    for col in df.columns:
        if str(col) not in excluded and profiler._is_binary(df[col]):
            return str(col)
    return None


def _n_predictors(df: pd.DataFrame, excluded: set[str]) -> int:
    return max(len([c for c in df.columns if str(c) not in excluded]), 0)


def _eval_prognostic(df: pd.DataFrame, hints: dict[str, Any]) -> dict[str, Any]:
    time_cols = profiler._follow_up_columns(df, hints)
    event_cols = profiler._event_columns(df, hints)
    reasons: list[str] = []
    if time_cols and event_cols:
        survival = True
        task_type = "survival"
        reasons.append(f"检测到随访时间列 {time_cols[0]} 与事件列 {event_cols[0]}，按生存结局建模")
        excluded = {time_cols[0], event_cols[0]}
        events: int | None = int(
            pd.to_numeric(df[event_cols[0]], errors="coerce").fillna(0).sum()
        )
    else:
        outcome = _binary_outcome_column(df, hints)
        if outcome is None:
            return {
                "applicable": False,
                "reasons": ["未检测到随访时间+事件列，也未检测到二分类结局列，无法构建预后模型"],
                "task_type": "classification",
                "models": _template_models("prognostic_model", survival=False),
                "charts": _template_charts("prognostic_model", survival=False),
                "sample_size": [_epv_advice(None, 0)],
            }
        survival = False
        task_type = "classification"
        reasons.append(f"未检测到随访列，但结局列 {outcome} 为二分类，按二分类预后建模")
        excluded = {outcome}
        events = _minority_count(df[outcome])
    n_features = _n_predictors(df, excluded)
    reasons.append(f"候选预测因子 {n_features} 个（已排除结局/随访列）")
    return {
        "applicable": True,
        "reasons": reasons,
        "task_type": task_type,
        "models": _template_models("prognostic_model", survival=survival),
        "charts": _template_charts("prognostic_model", survival=survival),
        "sample_size": [_epv_advice(events, n_features)],
    }


def _eval_risk_factor(df: pd.DataFrame, hints: dict[str, Any]) -> dict[str, Any]:
    outcome = _binary_outcome_column(df, hints)
    models = _template_models("risk_factor")
    charts = _template_charts("risk_factor")
    if outcome is None:
        return {
            "applicable": False,
            "reasons": ["未检测到二分类结局列，危险因素分析需要 0/1 结局"],
            "task_type": "classification",
            "models": models,
            "charts": charts,
            "sample_size": [_epv_advice(None, 0)],
        }
    n_features = _n_predictors(df, {outcome})
    events = _minority_count(df[outcome])
    return {
        "applicable": True,
        "reasons": [f"结局列 {outcome} 为二分类，候选预测因子 {n_features} 个"],
        "task_type": "classification",
        "models": models,
        "charts": charts,
        "sample_size": [_epv_advice(events, n_features)],
    }


def _eval_dose_response(df: pd.DataFrame, hints: dict[str, Any]) -> dict[str, Any]:
    outcome = profiler._outcome_column(df, hints, "")
    models = _template_models("dose_response")
    charts = _template_charts("dose_response")
    continuous = (
        outcome is not None
        and pd.api.types.is_numeric_dtype(df[outcome])
        and df[outcome].nunique(dropna=True) > 2
        and not profiler._is_binary(df[outcome])
    )
    if outcome is None or not continuous:
        return {
            "applicable": False,
            "reasons": ["未检测到连续型结局列，剂量反应分析需要连续结局与连续暴露"],
            "task_type": "regression",
            "models": models,
            "charts": charts,
            "sample_size": [_n_per_predictor_advice(len(df), 0)],
        }
    n_features = _n_predictors(df, {outcome})
    return {
        "applicable": True,
        "reasons": [f"结局列 {outcome} 为连续型，候选预测因子 {n_features} 个"],
        "task_type": "regression",
        "models": models,
        "charts": charts,
        "sample_size": [_n_per_predictor_advice(len(df), n_features)],
    }


def _eval_longitudinal(df: pd.DataFrame, hints: dict[str, Any]) -> dict[str, Any]:
    time_cols = profiler._time_columns(df)
    models = _template_models("longitudinal")
    charts = _template_charts("longitudinal")
    if not time_cols:
        return {
            "applicable": False,
            "reasons": ["未检测到时间索引列，纵向分析需要重复测量的时间信息"],
            "task_type": "regression",
            "models": models,
            "charts": charts,
            "sample_size": [_longitudinal_n_advice(len(df))],
        }
    return {
        "applicable": True,
        "reasons": [f"检测到时间索引列 {time_cols[0]}，记录数 {len(df)}"],
        "task_type": "regression",
        "models": models,
        "charts": charts,
        "sample_size": [_longitudinal_n_advice(len(df))],
    }


_EVALUATORS = {
    "prognostic_model": _eval_prognostic,
    "risk_factor": _eval_risk_factor,
    "dose_response": _eval_dose_response,
    "longitudinal": _eval_longitudinal,
}


def evaluate_templates(
    df: pd.DataFrame, hints: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """按数据集真实统计评估四类模板的适用性与样本量核对。"""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas.DataFrame")
    safe_hints = hints or {}
    results: list[dict[str, Any]] = []
    for template in TEMPLATES:
        evaluation = _EVALUATORS[template.key](df, safe_hints)
        results.append(
            {
                "key": template.key,
                "name": template.name,
                "description": template.description,
                **evaluation,
            }
        )
    return results
