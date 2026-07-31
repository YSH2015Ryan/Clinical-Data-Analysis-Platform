"""任务类型自动识别（docs/08 §1 engines/task_detection）。

规则流（§1.1）：时间列+事件0/1列 → survival；二分类候选结局 → classification；
多分类候选 → classification(多分类)；连续候选标签 → regression；否则 None
（识别失败 → 手动选择，API 层 422，T4.2）。

候选来源（§1.2）：词典语义识别（T2.3 recognize_semantic）+ 模式规则
（0/1 且列名含事件关键词 → 事件列；正数连续且与事件列成对 → 时间列候选）。
每个推断附置信度与理由（§1.3 输出契约）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.engines.columns import infer_dtype, recognize_semantic

# 模式规则置信度（低于词典匹配：§1.2 模式规则为次级证据）
_PATTERN_TIME_CONF = 0.6
_GENERIC_BINARY_CONF = 0.5
_GENERIC_MULTICLASS_CONF = 0.5
_FOLLOWUP_AS_REGRESSION_CONF = 0.6
_MULTICLASS_MAX_UNIQUE = 10
# 模式规则时间列名提示（正数连续 + 名含时间词 + 与事件列成对 → 时间列候选；
# 无名称约束会误吞 age/wbc 等任意正数指标列）
_TIME_NAME_HINTS = ("time", "days", "months", "years", "fu", "时间", "天数", "月", "年")
# 标识符列名提示（全唯一 + 名含 id → 不做结局候选，小样本同样排除）
_ID_NAME_HINTS = ("id", "编号")


@dataclass
class Candidate:
    column: str
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "confidence": round(self.confidence, 2)}


@dataclass
class TaskDetection:
    """docs/08 §1.3 输出契约（与 docs/14 TaskDetectionResult 一致）。"""

    recommended_task: str | None  # survival | classification | regression | None
    confidence: float
    reason: str
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    user_override: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_task": self.recommended_task,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "candidates": {
                key: [c.to_dict() for c in cands] for key, cands in self.candidates.items()
            },
            "user_override": self.user_override,
        }


def _is_binary(s: pd.Series) -> bool:
    values = set(s.dropna().unique().tolist())
    return bool(values) and values <= {0, 1}


def _has_hint(name: str, hints: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(h in lowered for h in hints)


def _sorted(cands: list[Candidate]) -> list[Candidate]:
    return sorted(cands, key=lambda c: c.confidence, reverse=True)


def detect_task(df: pd.DataFrame) -> TaskDetection:
    """识别任务类型；无法识别时 recommended_task=None（手动选择回退）。"""
    n = len(df)
    usable: dict[str, str] = {}  # col -> dtype
    for col in df.columns:
        dtype = infer_dtype(df[col])
        # id/datetime/text 不做结局候选；小样本时按列名 id 提示排除标识符
        if dtype in ("id", "datetime", "text"):
            continue
        if n < 10 and _has_hint(col, _ID_NAME_HINTS) and int(df[col].nunique()) >= n:
            continue
        usable[col] = dtype

    time_cands: list[Candidate] = []
    event_cands: list[Candidate] = []
    binary_label_cands: list[Candidate] = []
    multiclass_cands: list[Candidate] = []
    regression_cands: list[Candidate] = []

    for col, dtype in usable.items():
        s = df[col]
        sem = recognize_semantic(col, s)
        binary = _is_binary(s)
        if sem.semantic == "FollowUp" and dtype == "continuous" and sem.confidence >= 0.85:
            time_cands.append(Candidate(col, sem.confidence, sem.reason))
        if sem.semantic == "Event" and binary and sem.confidence >= 0.85:
            event_cands.append(Candidate(col, sem.confidence, f"{sem.reason}（0/1 取值）"))
        if binary:
            if sem.semantic in ("Label", "Event"):
                binary_label_cands.append(Candidate(col, sem.confidence, sem.reason))
            elif sem.semantic is None:
                binary_label_cands.append(Candidate(col, _GENERIC_BINARY_CONF, "0/1 二值列"))
        elif dtype == "categorical" and 3 <= int(s.nunique()) <= _MULTICLASS_MAX_UNIQUE:
            if sem.semantic == "Label":
                multiclass_cands.append(Candidate(col, sem.confidence, sem.reason))
            elif sem.semantic is None:
                multiclass_cands.append(
                    Candidate(col, _GENERIC_MULTICLASS_CONF, f"{int(s.nunique())} 个类别")
                )
        elif dtype == "continuous":
            if sem.semantic == "Label":
                regression_cands.append(Candidate(col, sem.confidence, sem.reason))
            elif sem.semantic == "FollowUp" and sem.confidence >= 0.85:
                regression_cands.append(
                    Candidate(col, _FOLLOWUP_AS_REGRESSION_CONF, f"{sem.reason}（无配对事件列）")
                )

    # 模式规则：正数连续 + 列名含时间词 + 与事件列成对出现 → 时间列候选（§1.2）
    if event_cands:
        known = {c.column for c in time_cands}
        for col, dtype in usable.items():
            if col in known or dtype != "continuous" or not _has_hint(col, _TIME_NAME_HINTS):
                continue
            s = df[col].dropna()
            if not s.empty and float(s.min()) >= 0:
                time_cands.append(
                    Candidate(col, _PATTERN_TIME_CONF, "正数连续且与事件列成对出现（模式规则）")
                )

    candidates = {
        "time_col": _sorted(time_cands),
        "event_col": _sorted(event_cands),
        "label_col": _sorted(binary_label_cands + multiclass_cands + regression_cands),
    }

    if time_cands and event_cands:
        t, e = _sorted(time_cands)[0], _sorted(event_cands)[0]
        return TaskDetection(
            recommended_task="survival",
            confidence=round(0.5 * (t.confidence + e.confidence), 2),
            reason=f"检测到生存时间列 {t.column}（{t.reason}）与事件列 {e.column}（{e.reason}）",
            candidates=candidates,
        )

    if binary_label_cands:
        top = _sorted(binary_label_cands)[0]
        return TaskDetection(
            recommended_task="classification",
            confidence=top.confidence,
            reason=f"检测到二分类结局候选列 {top.column}（{top.reason}）",
            candidates=candidates,
        )

    if multiclass_cands:
        top = _sorted(multiclass_cands)[0]
        return TaskDetection(
            recommended_task="classification",
            confidence=top.confidence,
            reason=f"检测到多分类结局候选列 {top.column}（{top.reason}）",
            candidates=candidates,
        )

    if regression_cands:
        top = _sorted(regression_cands)[0]
        return TaskDetection(
            recommended_task="regression",
            confidence=top.confidence,
            reason=f"检测到连续结局候选列 {top.column}（{top.reason}）",
            candidates=candidates,
        )

    return TaskDetection(
        recommended_task=None,
        confidence=0.0,
        reason="未识别到时间/事件/标签候选列，请手动选择任务类型",
        candidates=candidates,
    )
