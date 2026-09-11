"""智能任务顾问（T6.6 修复版，roadmap P0-1）

纪律（与 services/llm_tasks.py 一致）：
- 规则引擎（detect_task_from_profile）出结论：推荐任务、目标列、能否建模；
  LLM 只改写「整体评估」与「EDA 建议」的表达，不做判断（红线 8）；
- 分功能开关 task_recommend 门控（off/local/local_first/cloud）；
  off / LLM 不可用 / 输出不合格一律回退规则结果，主流程不阻塞；
- prompt 只含聚合元数据（行/列数、列名、类型、缺失率、唯一值数），
  禁止行级样本值（隐私红线：云端路径只出聚合统计）。

修复历史：旧版调用 LLMService 不存在的方法（is_available/chat）并读取
validation profile 不存在的键（data_type/semantic_type/...），异常被静默
吞掉，功能从未产出结果。本版以测试锁定真实接口与真实 profile 键。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import pandas as pd

from app.engines.llm_validators import hallucinated_numbers
from app.engines.task_detection import detect_task_from_profile

logger = logging.getLogger(__name__)

# 任务类型合法值（与 docs/08 状态机任务类型一致；eda 表示不适合建模）
_VALID_TASKS = {"classification", "regression", "survival", "eda"}

# 可直接建模的最低规则置信度（与 task_detection 语义支撑阈值一致）
_MIN_MODELING_CONF = 0.6

_ModelChoice = Literal["local", "cloud", "auto"]

# 分功能开关 → 模型策略（与 services/llm_tasks.switch_to_choice 同义；
# 引擎层不 import services，本地维护映射，off → 跳过 LLM 走规则回退）
_SWITCH_TO_CHOICE: dict[str, _ModelChoice] = {
    "local": "local",
    "local_first": "auto",
    "cloud": "cloud",
}


class _LLMCompletable(Protocol):
    """引擎所需的 LLM 最小接口（services/llm.LLMService 的结构子类型）。"""

    def complete(
        self,
        prompt: str,
        *,
        facts: dict[str, Any] | None = None,
        model_choice: _ModelChoice | None = None,
        temperature: float = 0.3,
        seed: int = 42,
        max_tokens: int = 600,
    ) -> str: ...


@dataclass
class TaskRecommendation:
    """任务类型推荐结果（前端 AIRecommendationCard 的 detail 契约）。"""

    recommended_tasks: list[str]
    recommended_targets: list[dict[str, Any]]  # [{"column", "reason", "task_type"}]
    unsuitable_tasks: dict[str, str]
    eda_suggestions: list[str]
    overall_assessment: str
    can_start_modeling: bool


class IntelligentTaskAdvisor:
    """智能任务顾问：规则结论 + 可选 LLM 表达增强。

    llm_service 可为 None（未初始化/部署无 LLM）：此时 analyze_dataset
    仍返回规则版推荐，保证 AI_RECOMMEND 卡在所有部署下都有真实内容。
    """

    def __init__(self, llm_service: _LLMCompletable | None = None):
        self.llm = llm_service

    def analyze_dataset(
        self,
        df: pd.DataFrame,
        column_profiles: list[dict[str, Any]],
        *,
        switch: str = "off",
        temperature: float = 0.3,
    ) -> TaskRecommendation:
        """分析数据集并给出任务推荐（规则为基线，LLM 增强表达）。"""
        base = self._rule_recommendation(column_profiles)
        choice = _SWITCH_TO_CHOICE.get(switch)
        if choice is None or self.llm is None:
            return base
        facts = self._build_facts(df, column_profiles, base)
        try:
            raw = self.llm.complete(
                self._prompt(facts),
                facts=facts,
                model_choice=choice,
                temperature=temperature,
                max_tokens=700,
            )
        except Exception as exc:
            logger.warning(f"task_advisor_llm_failed: {exc}")
            return base
        enhanced = self._parse_llm_output(raw, facts, df)
        if enhanced is None:
            return base
        # 结论字段以规则为准，LLM 只接管表达字段
        base.overall_assessment = enhanced["overall_assessment"] or base.overall_assessment
        if enhanced["eda_suggestions"]:
            base.eda_suggestions = enhanced["eda_suggestions"]
        return base

    # ------------------------------------------------------------------
    # 规则结论（唯一判断来源）
    # ------------------------------------------------------------------

    def _rule_recommendation(self, column_profiles: list[dict[str, Any]]) -> TaskRecommendation:
        det = detect_task_from_profile(column_profiles)
        if det.recommended_task is not None:
            targets = [
                {
                    "column": c.column,
                    "reason": c.reason,
                    "task_type": det.recommended_task,
                }
                for kind in ("time_col", "event_col", "label_col")
                for c in det.candidates.get(kind, [])[:2]
            ]
            return TaskRecommendation(
                recommended_tasks=[det.recommended_task],
                recommended_targets=targets,
                unsuitable_tasks={},
                eda_suggestions=[],
                overall_assessment=det.reason,
                can_start_modeling=det.confidence >= _MIN_MODELING_CONF,
            )
        return TaskRecommendation(
            recommended_tasks=["eda"],
            recommended_targets=[],
            unsuitable_tasks={
                "classification": "未识别到明确的分类结局列",
                "regression": "未识别到明确的连续结局列",
                "survival": "未识别到成对的随访时间列与事件列",
            },
            eda_suggestions=["描述性统计", "相关性分析", "分布与缺失模式可视化"],
            overall_assessment=det.reason,
            can_start_modeling=False,
        )

    # ------------------------------------------------------------------
    # LLM 表达增强（仅聚合元数据进 prompt，无行级数据）
    # ------------------------------------------------------------------

    def _build_facts(
        self,
        df: pd.DataFrame,
        column_profiles: list[dict[str, Any]],
        base: TaskRecommendation,
    ) -> dict[str, Any]:
        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": [
                {
                    "name": p["name"],
                    "type": p.get("inferred_type", "unknown"),
                    "semantic": p.get("semantic"),
                    "missing_rate": p.get("missing_rate", 0.0),
                    "unique_count": p.get("unique", 0),
                }
                for p in column_profiles
            ],
            "rule_conclusion": {
                "recommended_tasks": base.recommended_tasks,
                "recommended_targets": [t["column"] for t in base.recommended_targets],
                "can_start_modeling": base.can_start_modeling,
                "reason": base.overall_assessment,
            },
        }

    def _prompt(self, facts: dict[str, Any]) -> str:
        facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
        return f"""你是临床数据分析顾问。规则引擎已给出以下数据集的任务识别结论，
请用专业、通俗的中文改写「整体评估」，并补充 2-4 条探索性分析建议。

【输出要求】
- 只输出 JSON 对象，不要输出任何其他文字（不要解释、不要 Markdown 代码块）
- 格式：{{"overall_assessment": "整体评估（60-150 字）", "eda_suggestions": ["建议1", "建议2"]}}
- 不得改变规则引擎的结论；不得编造 Facts 中不存在的数值、列名或分析类型
- 只引用 Facts 中出现的列名与数值

Facts:
{facts_json}

直接输出 JSON 对象："""

    def _parse_llm_output(
        self, raw: str, facts: dict[str, Any], df: pd.DataFrame
    ) -> dict[str, Any] | None:
        """解析 LLM 输出；结构/列名白名单/幻觉数值任一不合格 → None（回退规则）。"""
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        assessment = str(data.get("overall_assessment") or "").strip()
        suggestions_raw = data.get("eda_suggestions") or []
        suggestions = (
            [str(s).strip() for s in suggestions_raw if str(s).strip()]
            if isinstance(suggestions_raw, list)
            else []
        )
        real_columns = {str(c) for c in df.columns}
        text_all = " ".join([assessment, *suggestions])
        # 列名白名单：文本中出现「」或 "列" 语境的新列名视为编造——
        # 简化为：含「」括注且括注内容不是真实列名 → 拒绝
        for quoted in _quoted_spans(text_all):
            if quoted not in real_columns and quoted not in _VALID_TASKS:
                logger.warning(f"task_advisor_invented_column: {quoted}")
                return None
        # 幻觉数值拦截：表达文本中的数值必须来自 facts
        if hallucinated_numbers(text_all, facts):
            logger.warning("task_advisor_hallucination")
            return None
        return {"overall_assessment": assessment, "eda_suggestions": suggestions}


def _quoted_spans(text: str) -> list[str]:
    """提取「」/「"..."」括注内容（LLM 编造列名常以括注形式出现）。"""
    import re

    spans = re.findall(r"「([^」]+)」", text)
    spans += re.findall(r'"([^"]{1,30})"', text)
    return spans
