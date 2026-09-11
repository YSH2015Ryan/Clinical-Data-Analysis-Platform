"""LLM 业务接线（T6.7，roadmap P1）。

三处业务的统一入口，均遵循：
- LLM 只做表达与推理增强，不做计算；所有数字必须来自引擎 facts（红线 8）；
- 分功能开关（off/local/local_first/cloud）门控，LLM 不可用或输出不合格时
  一律回退规则/模板输出，主流程不阻塞；
- 云端路径由 LLMService.complete 内的隐私守卫兜底（只发聚合统计与列元数据）。
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.engines.llm_validators import hallucinated_numbers, numbers_in

from .settings import FeatureSwitch

if TYPE_CHECKING:
    from .llm import LLMService, ModelChoice

logger = logging.getLogger(__name__)

# 研究问题图表建议白名单（与报告图表能力对齐，防 LLM 编造不存在的图）
_CHART_WHITELIST = [
    "ROC 曲线",
    "校准曲线",
    "决策曲线（DCA）",
    "混淆矩阵",
    "特征重要性图",
    "预测值-实测值散点图",
    "KM 生存曲线",
    "HR 森林图",
    "基线特征表（Table 1）",
]

# 校验解释的长度接受区间（字）
_EXPLAIN_MIN_LEN = 30
_EXPLAIN_MAX_LEN = 300


def switch_to_choice(switch: FeatureSwitch) -> "ModelChoice | None":
    """分功能开关 → 模型策略；off → None（调用方跳过 LLM，走规则回退）。"""
    mapping: dict[str, ModelChoice] = {
        "local": "local",
        "local_first": "auto",
        "cloud": "cloud",
    }
    return mapping.get(switch)


# ---------------------------------------------------------------------------
# 1. 研究画像增强：规则结论 → 2-3 个可回答的研究问题
# ---------------------------------------------------------------------------


def _research_questions_prompt(facts: dict[str, Any]) -> str:
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
    charts = "、".join(_CHART_WHITELIST)
    return f"""你是医学科研设计专家。
基于以下数据集画像与规则引擎结论，提出 2-3 个能用该数据回答的临床研究问题。

【输出要求】
- 只输出 JSON 数组，不要输出任何其他文字（不要解释、不要 Markdown 代码块）
- 数组含 2-3 个元素，每个元素格式：
  {{"question": "研究问题（一句话）", "design": "研究设计建议（一句话）",
    "models": ["模型名"], "charts": ["图表名"]}}
- models 只能从 Facts 的 recommended_models 中选取
- charts 只能从此白名单选取：{charts}
- 不得编造 Facts 中不存在的数值、列名或模型名

Facts:
{facts_json}

直接输出 JSON 数组："""


def _parse_questions(raw: str, facts: dict[str, Any]) -> list[dict[str, Any]] | None:
    """解析 LLM 输出为研究问题列表；结构/白名单/幻觉数值任一不合格 → 丢弃该条。"""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except (TypeError, ValueError):
        return None
    if not isinstance(data, list):
        return None

    allowed_models = {str(m) for m in facts.get("recommended_models") or []}
    questions: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        design = str(item.get("design") or "").strip()
        if not question or not design:
            continue
        models = [str(m) for m in (item.get("models") or []) if str(m) in allowed_models]
        charts = [str(c) for c in (item.get("charts") or []) if str(c) in _CHART_WHITELIST]
        # 幻觉拦截：问题/设计文本中的数值必须来自 Facts
        if hallucinated_numbers(f"{question} {design}", facts):
            logger.warning(f"research_question_hallucination: {question[:40]}")
            continue
        questions.append(
            {"question": question, "design": design, "models": models, "charts": charts}
        )
        if len(questions) >= 3:
            break
    return questions or None


def generate_research_questions(
    service: "LLMService",
    facts: dict[str, Any],
    switch: FeatureSwitch,
    temperature: float = 0.3,
) -> list[dict[str, Any]] | None:
    """研究画像 LLM 增强：返回研究问题列表；失败/关闭/输出不合格 → None（规则结果兜底）。

    Args:
        service: LLM 服务实例
        facts: 规则引擎 detect_research_direction 输出 + 行列规模 + 列名（元数据）
        switch: research_profile 分功能开关
        temperature: 生成温度
    """
    choice = switch_to_choice(switch)
    if choice is None:
        return None
    try:
        raw = service.complete(
            _research_questions_prompt(facts),
            facts=facts,
            model_choice=choice,
            temperature=temperature,
            max_tokens=700,
        )
    except Exception as exc:
        logger.warning(f"research_questions_llm_failed: {exc}")
        return None
    return _parse_questions(raw, facts)


# ---------------------------------------------------------------------------
# 2. 报告解读段落：真实指标 → 学术段落（复用 generate_interpretation 验证链）
# ---------------------------------------------------------------------------

INTERPRETATION_SECTIONS = ("model_comparison", "performance", "clinical_interpretation")


def _citable_numbers(facts: dict[str, Any], cap: int = 40) -> list[float]:
    """facts 全量数值域（含结论文字中的数字）去重截断——供 LLM 引用与幻觉校验。

    generate_interpretation 的幻觉校验只识别数值类型字段；引擎结论字符串
    （如「p=0.032，差异有统计学意义」）里的真实数字需显式纳入合法数值域，
    否则 LLM 引用真实结论数字会被误判为幻觉。
    """
    seen: list[float] = []
    for num in numbers_in(facts):
        if not any(abs(num - s) < 1e-12 for s in seen):
            seen.append(num)
        if len(seen) >= cap:
            break
    return seen


def generate_report_interpretations(
    service: "LLMService",
    facts_by_section: dict[str, dict[str, Any]],
    switch: FeatureSwitch,
    temperature: float = 0.3,
) -> dict[str, str]:
    """逐章节生成解读段落；单章节失败只影响该章节（其余章节与模板拼句兜底）。

    Returns:
        {section_type: paragraph}，仅含生成且验证成功的章节；全失败 → 空 dict。
    """
    choice = switch_to_choice(switch)
    if choice is None:
        return {}
    paragraphs: dict[str, str] = {}
    for section_type, facts in facts_by_section.items():
        if section_type not in INTERPRETATION_SECTIONS or not facts:
            continue
        try:
            paragraphs[section_type] = service.generate_interpretation(
                facts={**facts, "citable_numbers": _citable_numbers(facts)},
                section_type=section_type,
                model_choice=choice,
                temperature=temperature,
            )
        except Exception as exc:
            logger.warning(f"report_interpretation_failed: {section_type}: {exc}")
    return paragraphs


# ---------------------------------------------------------------------------
# 3. 校验报错自然语言解释：Issue + 富文案 → 人话版修复指引
# ---------------------------------------------------------------------------


def _issue_explain_prompt(issue: dict[str, Any]) -> str:
    facts = {
        "column": issue.get("column"),
        "message": issue.get("message"),
        "suggestion": issue.get("suggestion"),
        "affected_rows": issue.get("affected_rows"),
        "guidance": issue.get("guidance"),
    }
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
    return f"""你是医疗数据平台的助手。请把以下数据校验问题用通俗中文解释给没有统计背景的临床医生，
并指出最推荐的一种修复操作。

【输出要求】
- 一段 60-150 字的通俗解释，不要用序号、不要分点
- 不要出现规则编号（如 RV201）和技术术语（如「主键」「插补」），用大白话
- 语气温和，先说明「是什么问题」，再说「建议怎么处理」
- 数值只能引用问题信息中出现的数值，不得编造

问题信息:
{facts_json}

直接输出解释段落："""


def explain_validation_issues(
    service: "LLMService",
    issues: list[dict[str, Any]],
    switch: FeatureSwitch,
    temperature: float = 0.3,
    max_issues: int = 5,
) -> int:
    """为阻塞级 Issue 生成「人话版」解释，就地写入 issue["llm_explanation"]（T6.1 衔接）。

    只处理 severity=blocker 的前 max_issues 条（控制延迟）；单条失败跳过，
    不影响其他条与主流程。

    Returns:
        成功写入解释的条数。
    """
    choice = switch_to_choice(switch)
    if choice is None:
        return 0
    explained = 0
    for issue in issues:
        if explained >= max_issues:
            break
        if issue.get("severity") != "blocker":
            continue
        try:
            raw = service.complete(
                _issue_explain_prompt(issue),
                facts=issue,
                model_choice=choice,
                temperature=temperature,
                max_tokens=300,
            )
        except Exception as exc:
            logger.warning(f"issue_explain_failed: {issue.get('rule_id')}: {exc}")
            continue
        text = re.sub(r"\s+", " ", raw).strip()
        if not (_EXPLAIN_MIN_LEN <= len(text) <= _EXPLAIN_MAX_LEN):
            logger.warning(f"issue_explain_bad_length: {issue.get('rule_id')}: {len(text)}")
            continue
        if hallucinated_numbers(text, issue):
            logger.warning(f"issue_explain_hallucination: {issue.get('rule_id')}")
            continue
        issue["llm_explanation"] = text
        explained += 1
    return explained


# ---------------------------------------------------------------------------
# 4. 对话式迭代（T6.13）："如果把 X 当协变量会怎样" → 回答 + 结构化重跑建议
# ---------------------------------------------------------------------------


def _iteration_prompt(question: str, facts: dict[str, Any]) -> str:
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
    return f"""你是医学统计建模顾问。研究者基于已完成的模型比较运行提问，请回答并给出重跑建议。

【输出要求】
- 只输出 JSON 对象，不要输出任何其他文字（不要解释、不要 Markdown 代码块）
- 格式：{{"answer": "回答（80-200 字，通俗但专业）",
  "summary": "重跑建议一句话",
  "add_features": ["建议纳入的协变量列名"],
  "drop_features": ["建议剔除的列名"],
  "selected_models": ["建议的模型集合"] 或 null}}
- add_features / drop_features 只能从 Facts 的 available_columns 中选取，空则给 []
- selected_models 只能从 Facts 的 available_models 中选取；无需调整模型则给 null
- 数值只能引用 Facts 中出现的数值，不得编造任何统计量
- 必须说明：协变量的实际影响需要重跑后以真实指标判断

研究者问题：{question}

Facts:
{facts_json}

直接输出 JSON 对象："""


def _parse_iteration_advice(raw: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    """解析 LLM 迭代输出；结构/白名单/幻觉数值任一不合格 → None（调用方回退规则版）。"""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    answer = str(data.get("answer") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not answer or not summary:
        return None
    columns = {str(c) for c in facts.get("available_columns") or []}
    models = {str(m) for m in facts.get("available_models") or []}
    add = [str(c) for c in (data.get("add_features") or []) if str(c) in columns]
    drop = [str(c) for c in (data.get("drop_features") or []) if str(c) in columns]
    selected_raw = data.get("selected_models")
    selected = (
        [str(m) for m in selected_raw if str(m) in models]
        if isinstance(selected_raw, list)
        else None
    )
    if not add and not drop and not selected:
        return None  # 无实质建议 → 回退规则版（避免空建议卡片）
    # 幻觉拦截：回答/摘要中的数值必须来自 Facts
    if hallucinated_numbers(f"{answer} {summary}", facts):
        logger.warning("iteration_advice_hallucination")
        return None
    return {
        "answer": answer,
        "suggestion": {
            "summary": summary,
            "add_features": add,
            "drop_features": drop,
            "selected_models": selected,
        },
    }


def generate_iteration_advice(
    service: "LLMService",
    question: str,
    facts: dict[str, Any],
    switch: FeatureSwitch,
    temperature: float = 0.3,
) -> dict[str, Any] | None:
    """LLM 迭代建议；关闭/失败/输出不合格 → None（调用方用 rule_based_advice 兜底）。"""
    choice = switch_to_choice(switch)
    if choice is None:
        return None
    try:
        raw = service.complete(
            _iteration_prompt(question, facts),
            facts=facts,
            model_choice=choice,
            temperature=temperature,
            max_tokens=600,
        )
    except Exception as exc:
        logger.warning(f"iteration_advice_llm_failed: {exc}")
        return None
    return _parse_iteration_advice(raw, facts)
