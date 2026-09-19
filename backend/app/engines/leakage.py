"""Deterministic P0 leakage and prediction-time checks.

This module is deliberately independent from API, Celery and ORM layers. It emits
structured evidence; callers decide whether a finding blocks a run or requires
explicit researcher confirmation.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LeakageFinding:
    code: str
    severity: str
    message: str
    columns: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "columns": list(self.columns),
            "evidence": self.evidence,
            "recommended_action": self.recommended_action,
        }


@dataclass(frozen=True)
class LeakageInspection:
    findings: tuple[LeakageFinding, ...]

    @property
    def has_blocking_issue(self) -> bool:
        return any(f.severity == "blocker" for f in self.findings)

    @property
    def has_gate_issue(self) -> bool:
        """updateplan §72：blocker 或 critical 级发现触发人工门（Exploratory Mode 确认）。"""
        return any(f.severity in ("blocker", "critical") for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "has_blocking_issue": self.has_blocking_issue,
            "has_gate_issue": self.has_gate_issue,
        }


def _normalized(name: str) -> str:
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())


# updateplan §24：日期派生目标与日期族特征的归一化词表（中英文）
_DATE_TARGET_TOKENS = (
    "monthgroup",
    "dategroup",
    "yeargroup",
    "seasongroup",
    "quartergroup",
    "weekgroup",
    "daygroup",
    "月份分组",
    "日期分组",
)
_DATE_FEATURE_TOKENS = (
    "month",
    "year",
    "season",
    "quarter",
    "week",
    "day",
    "date",
    "jieqi",
    "月份",
    "日期",
    "年份",
    "季节",
    "季度",
    "节气",
)


_NAME_GENERIC_TOKENS = {
    "status",
    "result",
    "group",
    "final",
    "flag",
    "type",
    "code",
    "class",
    "level",
    "value",
}


def _name_tokens(name: str) -> set[str]:
    """按非字母数字切词并小写（diabetes_result → {diabetes, result}）。"""
    token, tokens = [], []
    for ch in str(name).lower():
        if ch.isalnum():
            token.append(ch)
        elif token:
            tokens.append("".join(token))
            token = []
    if token:
        tokens.append("".join(token))
    return set(tokens)


def _name_similarity_columns(df: pd.DataFrame, target_col: str) -> list[str]:
    """§21：与目标共享非通用词根（长度 ≥3）的特征 → 疑似语义泄漏。

    双向子串或共享词根均命中；通用词（status/result/group 等）不构成证据，
    避免 month_group / date_group 类假阳性（该场景由 DATE_DERIVED_TARGET 覆盖）。
    """
    norm_target = _normalized(target_col)
    target_tokens = {t for t in _name_tokens(target_col) if len(t) >= 3} - _NAME_GENERIC_TOKENS
    if len(norm_target) < 3:
        return []
    hits: list[str] = []
    for col in df.columns:
        if col == target_col:
            continue
        norm = _normalized(str(col))
        if len(norm) < 3:
            continue
        if norm_target in norm or norm in norm_target:
            hits.append(str(col))
            continue
        feature_tokens = {t for t in _name_tokens(str(col)) if len(t) >= 3} - _NAME_GENERIC_TOKENS
        if target_tokens & feature_tokens:
            hits.append(str(col))
    return hits


def _date_derived_target_columns(df: pd.DataFrame, target_col: str) -> list[str]:
    """§24：目标名为日期派生词，且存在日期族特征列 → 返回这些特征列。"""
    norm_target = _normalized(target_col)
    if not any(tok in norm_target for tok in _DATE_TARGET_TOKENS):
        return []
    hits: list[str] = []
    for col in df.columns:
        if col == target_col:
            continue
        norm = _normalized(str(col))
        if any(tok in norm for tok in _DATE_FEATURE_TOKENS):
            hits.append(str(col))
    return hits


def _target_proxy_columns(df: pd.DataFrame, target_col: str) -> list[str]:
    target = df[target_col]
    proxies: list[str] = []
    for col in df.columns:
        if col == target_col:
            continue
        series = df[col]
        if len(series) != len(target):
            continue
        if series.equals(target):
            proxies.append(str(col))
            continue
        if pd.api.types.is_numeric_dtype(series) and pd.api.types.is_numeric_dtype(target):
            corr = series.corr(target)
            if pd.notna(corr) and abs(float(corr)) >= 0.999999:
                proxies.append(str(col))
    return proxies


def inspect_leakage(
    df: pd.DataFrame,
    *,
    target_col: str,
    group_col: str | None = None,
    prediction_time_col: str | None = None,
    feature_time_columns: dict[str, Any] | None = None,
    temporal: bool = False,
) -> LeakageInspection:
    """Inspect target proxies, repeated groups and prediction-time violations.

    ``feature_time_columns`` contains already-resolved availability timestamps or
    comparable values. The engine does not guess clinical dates from free text.
    """
    findings: list[LeakageFinding] = []
    if target_col not in df.columns:
        findings.append(
            LeakageFinding(
                "TARGET_COLUMN_MISSING", "blocker", f"目标列 {target_col} 不存在", (target_col,)
            )
        )
        return LeakageInspection(tuple(findings))

    proxies = _target_proxy_columns(df, target_col)
    if proxies:
        findings.append(
            LeakageFinding(
                "TARGET_PROXY",
                "blocker",
                "检测到与目标完全相同或近乎完全相关的候选预测变量",
                tuple(proxies),
                {"target_col": target_col, "correlation_threshold": 0.999999},
                "确认变量是否为结局直接记录、结局后变量或数据复制；在预测前不可用时移除。",
            )
        )

    name_hits = [c for c in _name_similarity_columns(df, target_col) if c not in proxies]
    if name_hits:
        findings.append(
            LeakageFinding(
                "NAME_SIMILARITY",
                "warning",
                f"特征名与目标 {target_col} 相似，疑似语义泄漏（名称含目标词根）",
                tuple(name_hits),
                {"target_col": target_col, "rule": "normalized_substring"},
                "确认这些变量是否由目标派生或记录于结局之后；如是则移除。",
            )
        )

    date_hits = _date_derived_target_columns(df, target_col)
    if date_hits:
        findings.append(
            LeakageFinding(
                "DATE_DERIVED_TARGET",
                "critical",
                f"目标 {target_col} 疑似可由日期族变量确定性重建，AUC 可能反映目标重建而非预测能力",
                tuple(date_hits),
                {"target_col": target_col, "rule": "date_family_tokens"},
                "核查目标定义与日期变量的派生关系；建模前移除可重建目标的日期族变量，"
                "或在报告中明确标注性能可能虚高。",
            )
        )

    if group_col and group_col in df.columns:
        duplicate_groups = int(df[group_col].duplicated(keep=False).sum())
        if duplicate_groups:
            findings.append(
                LeakageFinding(
                    "DUPLICATE_PATIENT",
                    "warning",
                    "同一患者/组出现多条记录，随机切分会造成患者级泄漏风险",
                    (group_col,),
                    {
                        "group_col": group_col,
                        "duplicate_rows": duplicate_groups,
                        "duplicate_groups": int(
                            df.loc[df[group_col].duplicated(keep=False), group_col].nunique()
                        ),
                    },
                    "使用 group-aware validation，并确认重复记录代表独立时间点还是重复录入。",
                )
            )

    if temporal and not prediction_time_col:
        findings.append(
            LeakageFinding(
                "PREDICTION_TIME_UNDEFINED",
                "blocker",
                "时间相关分析未定义 prediction time，无法判断预测变量在时点上是否可用",
                (),
                {},
                "提供 time-zero/prediction_time 列，并指定时间感知验证策略。",
            )
        )
    if prediction_time_col and prediction_time_col not in df.columns:
        findings.append(
            LeakageFinding(
                "PREDICTION_TIME_MISSING",
                "blocker",
                f"prediction time 列 {prediction_time_col} 不存在",
                (prediction_time_col,),
                {},
                "核对时间列名称或补充分析计划中的 prediction time 定义。",
            )
        )

    if prediction_time_col and feature_time_columns:
        prediction_times = pd.to_datetime(df[prediction_time_col], errors="coerce")
        for col, available_at in feature_time_columns.items():
            if col not in df.columns:
                continue
            availability = pd.to_datetime(available_at, errors="coerce")
            if pd.isna(availability):
                continue
            future_rows = int((availability > prediction_times).sum())
            if future_rows:
                findings.append(
                    LeakageFinding(
                        "FUTURE_FEATURE",
                        "blocker",
                        f"变量 {col} 在 prediction time 之后才可获得",
                        (col, prediction_time_col),
                        {"future_rows": future_rows, "available_at": str(availability)},
                        "移除该变量或重新定义预测时点；不得将未来信息用于当前预测。",
                    )
                )

    # An ID-like column with repeated rows is a useful warning even when the caller
    # did not explicitly configure group_col; it never silently becomes a group key.
    for col in df.columns:
        norm = _normalized(str(col))
        if (
            norm in {"patientid", "subjectid", "personid", "患者id", "患者编号"}
            and col != group_col
        ):
            repeated = int(df[col].duplicated(keep=False).sum())
            if repeated:
                findings.append(
                    LeakageFinding(
                        "PATIENT_ID_NOT_CONFIGURED",
                        "warning",
                        f"检测到患者标识列 {col}，但未配置 group_col",
                        (str(col),),
                        {"duplicate_rows": repeated},
                        "将该列配置为 group_col，避免同一患者跨训练/验证折。",
                    )
                )
    return LeakageInspection(tuple(findings))
