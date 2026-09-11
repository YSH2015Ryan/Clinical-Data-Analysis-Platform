"""Rule-based research design profiler.

This module intentionally stays in the engines layer: it only inspects a
``pandas.DataFrame`` and optional user hints and has no web, database, or task
queue dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

_TIME_HINTS = (
    "time",
    "date",
    "datetime",
    "timestamp",
    "year",
    "month",
    "day",
    "period",
    "日期",
    "时间",
    "年月",
    "年份",
)
_FOLLOW_UP_HINTS = (
    "followup",
    "follow_up",
    "survival",
    "duration",
    "time",
    "days",
    "months",
    "years",
    "os",
    "pfs",
    "dfs",
    "随访",
    "生存",
)
_EVENT_HINTS = (
    "event",
    "death",
    "status",
    "censor",
    "recurrence",
    "progression",
    "outcome",
    "结局",
    "事件",
    "死亡",
    "复发",
    "进展",
)
_GROUP_HINTS = (
    "group",
    "case",
    "control",
    "cohort",
    "arm",
    "treatment",
    "分组",
    "病例",
    "对照",
)
_OUTCOME_HINTS = (
    "outcome",
    "target",
    "label",
    "response",
    "result",
    "结局",
    "标签",
    "结果",
    "y",
)


def _normalized(value: object) -> str:
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


def _name_has(name: object, hints: tuple[str, ...]) -> bool:
    normalized = _normalized(name)
    return any(_normalized(hint) in normalized for hint in hints)


def _is_binary(series: pd.Series) -> bool:
    values = series.dropna().unique().tolist()
    return bool(values) and set(values).issubset({0, 1, "0", "1"})


def _looks_datetime(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    if values.empty or not (
        pd.api.types.is_object_dtype(values) or pd.api.types.is_string_dtype(values)
    ):
        return False
    parsed = pd.to_datetime(values.head(1000), errors="coerce", format="mixed")
    return bool(parsed.notna().mean() >= 0.8)


def _time_columns(df: pd.DataFrame) -> list[str]:
    return [
        str(column)
        for column in df.columns
        if _looks_datetime(df[column]) or _name_has(column, _TIME_HINTS)
    ]


def _follow_up_columns(df: pd.DataFrame, hints: Mapping[str, Any]) -> list[str]:
    explicit = hints.get("time_column") or hints.get("time_col") or hints.get("follow_up_column")
    names = [str(explicit)] if explicit in df.columns else []
    for column in df.columns:
        name = str(column)
        if name in names:
            continue
        if _name_has(name, _FOLLOW_UP_HINTS) and pd.api.types.is_numeric_dtype(df[column]):
            names.append(name)
    return names


def _event_columns(df: pd.DataFrame, hints: Mapping[str, Any]) -> list[str]:
    explicit = hints.get("event_column") or hints.get("event_col")
    names = [str(explicit)] if explicit in df.columns else []
    for column in df.columns:
        name = str(column)
        if name not in names and _name_has(name, _EVENT_HINTS) and _is_binary(df[column]):
            names.append(name)
    return names


def _group_columns(df: pd.DataFrame, hints: Mapping[str, Any]) -> list[str]:
    explicit = hints.get("group_column") or hints.get("group_col")
    names = [str(explicit)] if explicit in df.columns else []
    for column in df.columns:
        name = str(column)
        if name in names or not _name_has(name, _GROUP_HINTS):
            continue
        if 2 <= int(df[column].nunique(dropna=True)) <= 3:
            names.append(name)
    return names


def _detect_study_type(df: pd.DataFrame, hints: Mapping[str, Any]) -> tuple[str, str, float]:
    requested = str(hints.get("research_type") or hints.get("study_type") or "").lower()
    aliases = {
        "cross-sectional": "cross_sectional",
        "cross sectional": "cross_sectional",
        "cross_sectional": "cross_sectional",
        "cohort": "cohort",
        "case-control": "case_control",
        "case_control": "case_control",
        "time-series": "time_series",
        "time series": "time_series",
        "time_series": "time_series",
    }
    if requested in aliases:
        return aliases[requested], "采用用户指定的研究类型", 0.98

    follow_up = _follow_up_columns(df, hints)
    events = _event_columns(df, hints)
    if follow_up and events:
        return "cohort", "检测到随访时间列和0/1事件列，符合队列/生存研究设计", 0.92

    time_columns = _time_columns(df)
    if time_columns:
        return "time_series", f"检测到时间索引列 {time_columns[0]}，符合时序研究设计", 0.88

    groups = _group_columns(df, hints)
    if groups:
        return "case_control", f"检测到二分类病例/对照分组列 {groups[0]}", 0.82

    return "cross_sectional", "未检测到随访、时间索引或病例/对照分组，按横断面研究处理", 0.70


def _outcome_column(df: pd.DataFrame, hints: Mapping[str, Any], research_type: str) -> str | None:
    explicit = hints.get("outcome") or hints.get("outcome_column") or hints.get("label_col")
    if explicit in df.columns:
        return str(explicit)
    excluded = set(_time_columns(df) + _follow_up_columns(df, hints) + _event_columns(df, hints))
    for column in df.columns:
        if str(column) not in excluded and _name_has(column, _OUTCOME_HINTS):
            return str(column)
    if research_type == "case_control":
        groups = _group_columns(df, hints)
        return groups[0] if groups else None
    return None


def _recommend_models(
    df: pd.DataFrame, research_type: str, hints: Mapping[str, Any] | None = None
) -> list[str]:
    if research_type == "cohort":
        return ["coxph", "rsf", "deepsurv"]
    if research_type == "time_series":
        return ["dlnm", "gam"]

    outcome = _outcome_column(df, hints or {}, research_type)
    if outcome is not None and _is_binary(df[outcome]):
        return ["logreg", "rf", "xgboost"]
    if outcome is not None and (
        pd.api.types.is_numeric_dtype(df[outcome]) and df[outcome].nunique(dropna=True) > 2
    ):
        return ["lasso", "rf_reg", "xgboost_reg"]
    return ["logreg", "rf", "xgboost"]


def _recommend_journals(research_type: str) -> list[str]:
    return {
        "cohort": ["JAMA", "Lancet", "BMJ"],
        "time_series": ["Environmental Health Perspectives", "Epidemiology"],
        "case_control": ["American Journal of Epidemiology", "PLOS ONE", "BMC Public Health"],
        "cross_sectional": ["PLOS ONE", "BMC Public Health"],
    }.get(research_type, ["PLOS ONE"])


def detect_research_direction(
    df: pd.DataFrame, user_hints: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Detect study design and return rule-based model and journal suggestions."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas.DataFrame")
    hints: Mapping[str, Any] = user_hints or {}
    research_type, type_reason, confidence = _detect_study_type(df, hints)
    models = _recommend_models(df, research_type, hints)
    journals = _recommend_journals(research_type)
    return {
        "research_type": research_type,
        "recommended_models": models,
        "recommended_journals": journals,
        "confidence": round(confidence, 2),
        "reasoning": (
            f"{type_reason}。数据集包含 {len(df)} 行、{len(df.columns)} 列，"
            f"推荐模型 {', '.join(models)}，投稿方向包括 {', '.join(journals)}。"
        ),
    }
