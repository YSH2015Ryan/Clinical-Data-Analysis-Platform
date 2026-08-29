"""对话式迭代规则引擎（tasks/phase6 T6.13）：问题 → 结构化重跑建议。

纯规则实现（LLM 关闭或失败时的回退，也是 LLM 输出的白名单校验基准）：
- 问题中提到的真实列名 → add/drop_features；提到的未选模型 → selected_models 增补；
- 回答只引用 facts 中的真实数值（红线8：不虚构统计量）。

分层纪律：纯引擎，只依赖标准库；禁止 import fastapi/celery/sqlalchemy。
"""

import re
from typing import Any

# 剔除意图关键词（默认意图为「纳入协变量」）
_DROP_HINTS = ("去掉", "剔除", "移除", "删除", "不用", "排除")


def _mentioned(text: str, candidates: list[str]) -> list[str]:
    """text 中出现的候选词（长名优先，避免短名误匹配长名的一部分）。"""
    found: list[str] = []
    for name in sorted(candidates, key=len, reverse=True):
        if name and name in text and name not in found:
            found.append(name)
    return found


def rule_based_advice(question: str, facts: dict[str, Any]) -> dict[str, Any]:
    """规则版迭代建议；返回 {answer, suggestion|None}。

    facts 键：task_type / available_columns（不含结局列）/ available_models /
    selected_models / top_model / top_reason（含真实指标文本）。
    """
    columns = [str(c) for c in facts.get("available_columns") or []]
    available_models = [str(m) for m in facts.get("available_models") or []]
    selected = [str(m) for m in facts.get("selected_models") or []]
    top_model = str(facts.get("top_model") or "")
    top_reason = str(facts.get("top_reason") or "")

    mentioned_cols = _mentioned(question, columns)
    new_models = [m for m in _mentioned(question, available_models) if m not in selected]
    wants_drop = any(h in question for h in _DROP_HINTS)

    context = ""
    if top_model and top_reason:
        context = f"本次运行推荐 {top_model}（{top_reason}，来自交叉验证真实指标）。"

    suggestion: dict[str, Any] | None = None
    parts: list[str] = []
    if mentioned_cols:
        if wants_drop:
            suggestion = {
                "add_features": [],
                "drop_features": mentioned_cols,
                "selected_models": None,
            }
            parts.append(f"可在预处理中剔除 {'、'.join(mentioned_cols)} 后重跑，比较主指标变化。")
        else:
            suggestion = {
                "add_features": mentioned_cols,
                "drop_features": [],
                "selected_models": None,
            }
            parts.append(
                f"可把 {'、'.join(mentioned_cols)} 作为协变量纳入模型重跑；"
                "建议保持相同交叉验证方案，比较重跑前后主指标变化来判断其作用。"
            )
    if new_models:
        merged = [*selected, *new_models]
        suggestion = suggestion or {
            "add_features": [],
            "drop_features": [],
            "selected_models": None,
        }
        suggestion["selected_models"] = merged
        parts.append(f"建议把 {'、'.join(new_models)} 加入模型集重跑，与现有模型同口径比较。")

    if parts:
        answer = context + "".join(parts)
    else:
        # 未识别到列/模型：如实回显无法匹配的词（含拉丁字母/数字的词片段），并给出提问指引
        tokens = [t for t in re.split(r"[，。！？、\s？?,.!「」]+", question) if t]
        unknown = [
            t
            for t in tokens
            if re.search(r"[A-Za-z0-9]", t) and t not in columns and t not in available_models
        ][:3]
        unknown_hint = f"（{'、'.join(unknown)} 不在数据集列或可用模型中）" if unknown else ""
        answer = (
            context
            + "未从问题中识别到数据集中的列名或可用模型"
            + unknown_hint
            + "。可以这样提问：「如果把某列当协变量会怎样」「去掉某列再跑」「加上某模型比较」。"
            "建议均需在向导中确认后重跑，影响以重跑后的真实指标为准。"
        )
    if suggestion is not None:
        suggestion["summary"] = parts[0] if parts else ""
    return {"answer": answer, "suggestion": suggestion}
