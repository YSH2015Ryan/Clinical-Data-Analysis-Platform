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


# T6.2:≥0.6 视为「有语义支撑」的回归候选(Label 词典 0.85+;FollowUp 派生 0.6)。
# 低于此值的泛猜(纯模式规则 0.5)不得压过有语义支撑的回归候选 ——
# 修复「无语义 0/1 标志列抢在回归前面」的偏置(tasks/phase6 T6.2)。
_SEMANTIC_BACKED_MIN_CONF = 0.6


def _decide(
    binary_label_cands: list[Candidate],
    multiclass_cands: list[Candidate],
    regression_cands: list[Candidate],
    candidates: dict[str, list[Candidate]],
) -> TaskDetection:
    """分类/回归决策(detect_task 与 detect_task_from_profile 共用,保证逻辑等价)。

    规则(T6.2):二分类/多分类的 top 候选若只是泛猜(conf<0.6 无语义),
    且存在有语义支撑的回归候选(conf≥0.6),则推荐回归;泛猜列保留在候选中。
    """
    sem_reg = _sorted([c for c in regression_cands if c.confidence >= _SEMANTIC_BACKED_MIN_CONF])
    for cands, kind in ((binary_label_cands, "二分类"), (multiclass_cands, "多分类")):
        if not cands:
            continue
        top = _sorted(cands)[0]
        if top.confidence < _SEMANTIC_BACKED_MIN_CONF and sem_reg:
            r = sem_reg[0]
            return TaskDetection(
                recommended_task="regression",
                confidence=r.confidence,
                reason=(
                    f"检测到连续结局候选列 {r.column}（{r.reason}）；"
                    f"列 {top.column}（{top.reason}）无语义命中，更像标志/协变量，已降级为候选"
                ),
                candidates=candidates,
            )
        return TaskDetection(
            recommended_task="classification",
            confidence=top.confidence,
            reason=f"检测到{kind}结局候选列 {top.column}（{top.reason}）",
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

    return _decide(binary_label_cands, multiclass_cands, regression_cands, candidates)


def detect_task_from_profile(column_profile: list[dict[str, Any]]) -> TaskDetection:
    """从已存储的 column_profile 直接推断任务类型，无需重新加载文件。

    与 detect_task(df) 逻辑完全等价，但所有列统计量（inferred_type / semantic /
    semantic_confidence / unique / min）均取自验证阶段已写入 DB 的 profile，
    响应时间从"下载+解析"降至毫秒级。

    binary 判定策略：
    - semantic in ("Event","Label") + unique==2 → 确定为 0/1 二值
    - semantic is None + unique==2              → 保守认为可能二值（confidence 0.5）
    - continuous 列 min==0, max==1, unique==2   → 确定为 0/1 二值
    """
    time_cands: list[Candidate] = []
    event_cands: list[Candidate] = []
    binary_label_cands: list[Candidate] = []
    multiclass_cands: list[Candidate] = []
    regression_cands: list[Candidate] = []

    for p in column_profile:
        name: str = p["name"]
        dtype: str = p.get("inferred_type", "")
        semantic: str | None = p.get("semantic")
        conf: float = float(p.get("semantic_confidence", 0.0))
        unique: int = int(p.get("unique", 0))
        p_min = p.get("min")
        p_max = p.get("max")

        # id / datetime / text 不做结局候选（与 detect_task 一致）
        if dtype in ("id", "datetime", "text"):
            continue

        # binary 判断：值域 ⊆ {0,1}
        if dtype == "continuous":
            binary = (p_min is not None and p_max is not None
                      and float(p_min) == 0.0 and float(p_max) == 1.0 and unique == 2)
        else:
            # categorical unique==2：语义明确时确定为二值，否则保守认为可能
            binary = (unique == 2)

        # FollowUp 时间列候选
        if semantic == "FollowUp" and dtype == "continuous" and conf >= 0.85:
            time_cands.append(Candidate(name, conf, f"FollowUp 语义（置信度 {conf:.2f}）"))

        # Event 事件列候选
        if semantic == "Event" and binary and conf >= 0.85:
            event_cands.append(Candidate(name, conf, f"Event 语义（0/1 取值，置信度 {conf:.2f}）"))

        # 二值/多分类/回归结局候选
        if binary:
            if semantic in ("Label", "Event"):
                binary_label_cands.append(Candidate(name, conf, f"{semantic} 语义"))
            elif semantic is None:
                binary_label_cands.append(Candidate(name, _GENERIC_BINARY_CONF, "0/1 二值列"))
        elif dtype == "categorical" and 3 <= unique <= _MULTICLASS_MAX_UNIQUE:
            if semantic == "Label":
                multiclass_cands.append(Candidate(name, conf, f"Label 语义（{unique} 类）"))
            elif semantic is None:
                multiclass_cands.append(
                    Candidate(name, _GENERIC_MULTICLASS_CONF, f"{unique} 个类别")
                )
        elif dtype == "continuous":
            if semantic == "Label":
                regression_cands.append(Candidate(name, conf, f"Label 语义（连续值）"))
            elif semantic == "FollowUp" and conf >= 0.85:
                regression_cands.append(
                    Candidate(name, _FOLLOWUP_AS_REGRESSION_CONF, f"{semantic} 语义（无配对事件列）")
                )

    # 模式规则：正数连续 + 列名含时间词 → 时间列候选（event_cands 存在时）
    if event_cands:
        known = {c.column for c in time_cands}
        for p in column_profile:
            name = p["name"]
            if name in known or p.get("inferred_type") != "continuous":
                continue
            if not _has_hint(name, _TIME_NAME_HINTS):
                continue
            p_min = p.get("min")
            if p_min is not None and float(p_min) >= 0:
                time_cands.append(
                    Candidate(name, _PATTERN_TIME_CONF, "正数连续且与事件列成对出现（模式规则）")
                )

    candidates: dict[str, list[Candidate]] = {
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
    return _decide(binary_label_cands, multiclass_cands, regression_cands, candidates)
