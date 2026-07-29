"""列类型推断 + 列语义识别（docs/05 §2 步骤 E/F、docs/08 §1.2）。

- infer_dtype：连续/分类/日期/文本/ID 五类，数据驱动（不看列名）。
- recognize_semantic：词典匹配（中英文临床列名）→ token 匹配 → 模式规则，
  输出 semantic + confidence(0–1) + reason；供质量画像（T2.4）与
  任务识别（T4.1）复用，用户可在前端覆盖（docs/08 §1.2 人工兜底）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

from dataclasses import dataclass

import pandas as pd

# ---------- 类型推断（05 §2：连续/分类/日期/文本/ID） ----------

_MAX_CATEGORICAL_UNIQUE = 50  # 超出视为文本（RV601 高基数警告的判定线）
_MAX_INT_CATEGORICAL_UNIQUE = 10  # 整数列唯一值 ≤10 视为分类（如分级评分）
_ID_MIN_ROWS = 10  # 小样本不做 ID 判定
_TEXT_AVG_LEN = 50  # 平均长度超过视为自由文本
_NUMERIC_PARSE_RATIO = 0.9  # 字符串列 ≥90% 可转数值 → 数值意图（非法值交 RV301）
_DATETIME_PARSE_RATIO = 0.8
_DATETIME_MIN_LEN = 6  # 日期字符串最短长度（防止 "1"/"2024" 误判）


def infer_dtype(s: pd.Series) -> str:
    """返回 continuous / categorical / datetime / text / id 之一。"""
    non_null = s.dropna()
    if len(non_null) == 0:
        return "text"
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return "datetime"
    if pd.api.types.is_bool_dtype(non_null):
        return "categorical"
    if pd.api.types.is_numeric_dtype(non_null):
        nunique = non_null.nunique()
        if nunique <= 2:
            return "categorical"
        if pd.api.types.is_integer_dtype(non_null) and nunique <= _MAX_INT_CATEGORICAL_UNIQUE:
            return "categorical"
        return "continuous"
    # 字符串/object 列
    strs = non_null.astype(str)
    numeric_ratio = pd.to_numeric(strs, errors="coerce").notna().mean()
    if numeric_ratio >= _NUMERIC_PARSE_RATIO:
        return "continuous"
    if _looks_like_datetime(strs):
        return "datetime"
    n = len(strs)
    nunique = strs.nunique()
    if n >= _ID_MIN_ROWS and nunique == n:
        return "id"
    if strs.str.len().mean() > _TEXT_AVG_LEN:
        return "text"
    if nunique > _MAX_CATEGORICAL_UNIQUE:
        return "text"
    return "categorical"


def _looks_like_datetime(strs: pd.Series) -> bool:
    if strs.str.len().median() < _DATETIME_MIN_LEN:
        return False
    sample = strs.head(1000)
    parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    return bool(parsed.notna().mean() >= _DATETIME_PARSE_RATIO)


# ---------- 语义识别词典（08 §1.2：中英文临床列名，用户可扩展/覆盖） ----------

SEMANTIC_DICT: dict[str, tuple[str, ...]] = {
    "Age": ("age", "age_at_dx", "ageatdx", "age_at_diagnosis", "年龄", "确诊年龄", "患者年龄"),
    "Gender": ("gender", "sex", "性别"),
    "Diagnosis": ("diagnosis", "dx", "disease", "诊断", "疾病诊断", "疾病"),
    "FollowUp": (
        "os",
        "os_months",
        "os_days",
        "os_years",
        "pfs",
        "dfs",
        "survival_time",
        "followup",
        "follow_up",
        "生存时间",
        "随访",
        "随访时间",
    ),
    "Event": (
        "death",
        "event",
        "status",
        "censor",
        "recurrence",
        "progression",
        "死亡",
        "结局",
        "事件",
        "复发",
        "进展",
    ),
    "Label": ("label", "target", "outcome", "group", "标签", "分组"),
}

# 模式规则关键词（08 §1.2：0/1 且列名含 event/death/recur → 事件列）
_EVENT_NAME_HINTS = ("event", "death", "recur", "status", "死亡", "结局", "复发", "进展", "事件")


@dataclass(frozen=True)
class ColumnSemantic:
    semantic: str | None
    confidence: float  # 0–1；semantic 为 None 时恒为 0.0
    reason: str


def _normalize(name: str) -> str:
    """小写并去除非字母数字字符（保中文），使 os_months/OS MONTHS/OS-MONTHS 等价。"""
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())


# 预计算规范化词典：normalized_name -> semantic
_NORMALIZED_DICT: dict[str, str] = {
    _normalize(alias): semantic for semantic, aliases in SEMANTIC_DICT.items() for alias in aliases
}


def _is_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _tokens(name: str) -> list[str]:
    """按非字母数字切分（中文不分词，保持原样供子串匹配）。"""
    token, tokens = [], []
    for ch in str(name).lower():
        if ch.isalnum():
            token.append(ch)
        elif token:
            tokens.append("".join(token))
            token = []
    if token:
        tokens.append("".join(token))
    return tokens


def recognize_semantic(name: str, s: pd.Series) -> ColumnSemantic:
    """列名 + 取值 → 语义识别。优先级：词典精确(1.0) > token/中文子串(0.9) > 模式规则(0.85)。"""
    norm = _normalize(name)
    if not norm:
        return ColumnSemantic(None, 0.0, "列名为空")
    hit = _NORMALIZED_DICT.get(norm)
    if hit is not None:
        return ColumnSemantic(hit, 1.0, f"词典精确匹配「{name}」")
    # token 匹配（ASCII 词边界，避免 storage→age 误判）；中文条目走子串匹配
    name_tokens = set(_tokens(name))
    for alias_norm, semantic in _NORMALIZED_DICT.items():
        if _is_cjk(alias_norm):
            if alias_norm in norm:
                return ColumnSemantic(semantic, 0.9, f"中文子串匹配「{alias_norm}」")
        elif alias_norm in name_tokens:
            return ColumnSemantic(semantic, 0.9, f"词元匹配「{alias_norm}」")
    # 模式规则：0/1 取值 + 事件关键词 → 事件列
    if _is_binary(s) and any(hint in norm for hint in _EVENT_NAME_HINTS):
        return ColumnSemantic("Event", 0.85, "0/1 取值且列名含事件关键词")
    return ColumnSemantic(None, 0.0, "未匹配")


def _is_binary(s: pd.Series) -> bool:
    non_null = s.dropna()
    if len(non_null) == 0:
        return False
    return set(pd.unique(non_null)).issubset({0, 1})
