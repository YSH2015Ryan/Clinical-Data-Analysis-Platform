"""ReportContext 聚合器（docs/10 §2-3；docs/18 T7.1）。

纯函数：worker/service 装配好 payload（DB + 存储产物）后，本模块把它组织为
10 章节 + 附录的报告上下文。缺数据的章节标记 applicable=False（「本次分析不适用」），
不报错；免责声明与可复现附录强制存在（CLAUDE.md §8）。
"""

import json
from typing import Any

from app.engines.reporting.analysis_status import compute_analysis_status
from app.engines.reporting.captions import caption_for
from app.engines.reporting.checklist import build_reporting_checklist
from app.engines.reporting.limitations import build_limitations
from app.engines.reporting.narratives import (
    build_clinical_guides,
    build_comparison_guide,
    build_explainability_guides,
    build_performance_guides,
)
from app.engines.reporting.redflags import detect_perfect_metric_redflag
from app.engines.reporting.ml_reviewer import review_ml
from app.engines.reporting.statistical_reviewer import review_methodology

DISCLAIMER = "本报告由 CDAP 自动生成，仅供科研参考，不构成临床诊断建议。"
NOT_APPLICABLE = "本次分析不适用"
INTERPRETATION_NOTICE = "本节内容由系统自动生成，仅供线索参考，需研究者核实后方可写入论文。"

SECTION_TITLES: dict[str, str] = {
    "overview": "1. 数据与研究对象",
    "quality": "2. 数据质量评估",
    "preprocessing": "3. 预处理流程",
    "methods": "4. 统计分析方法",
    "performance": "5. 模型性能",
    "comparison": "6. 模型比较与推荐",
    "explainability": "7. 特征重要性与可解释性",
    "clinical_interpretation": "8. 临床意义解读",
    "limitations": "9. 局限性",
    "checklist": "10. 报告规范自查（TRIPOD）",
    "conclusion": "11. 结论",
}

# 摘要/元信息中的任务类型中文标签（docs/10 §2 卷首）
TASK_LABELS: dict[str, str] = {
    "classification": "分类 / 风险预测",
    "regression": "回归 / 预后",
    "survival": "生存分析",
}

# 可解释性图表（归第 6 章），其余对比图表归第 5 章（docs/10 §2）
_EXPLAIN_KINDS = {"feature_importance", "hr_forest"}


def _na() -> dict[str, Any]:
    return {"note": NOT_APPLICABLE}


def _humanize_params(params: Any) -> str:
    """§3 预处理参数人性化（T6.15①）：dict → '键=值' 分号连接；空/非 dict → '—'。

    中文不转义（ensure_ascii=False）；嵌套结构紧凑 JSON 化。附录仍保留原始
    preprocess_steps 供可复现核对。
    """
    if not isinstance(params, dict) or not params:
        return "—"
    parts = []
    for key, value in params.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        parts.append(f"{key}={value}")
    return "；".join(parts)


def _section(key: str, applicable: bool, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "title": SECTION_TITLES[key],
        "applicable": applicable,
        "data": data if applicable else _na(),
    }


def _interpretation_statements(charts: list[dict[str, Any]]) -> list[str]:
    """从真实产物生成模板化描述（HR 行 / 重要性 Top 特征）。"""
    statements: list[str] = []
    for chart in charts:
        if chart.get("kind") == "hr_forest":
            for model in (chart.get("data") or {}).get("models", []):
                for row in model.get("rows", [])[:5]:
                    statements.append(
                        f"{model['model_key']}：{row['feature']} 的 HR={row['hr']:.2f}"
                        f"（95% CI [{row['ci_lower']:.2f}, {row['ci_upper']:.2f}]）"
                    )
        if chart.get("kind") == "feature_importance":
            features = (chart.get("data") or {}).get("features", [])
            if features:
                top = "、".join(str(f) for f in features[:3])
                statements.append(f"跨模型共识的重要特征（按归一化重要性排序）：{top}。")
    return statements


def _build_abstract(
    payload: dict[str, Any],
    run: dict[str, Any],
    target_summary: dict[str, Any] | None,
    comparison: dict[str, Any] | None,
    conclusion_text: str | None,
) -> dict[str, str]:
    """结构化摘要（docs/10 §2 卷首）：目的/方法/结果/结论，全部由真实计算值填充。"""
    abstract: dict[str, str] = {}
    task_label = TASK_LABELS.get(str(run.get("task_type") or ""), str(run.get("task_type") or ""))
    dataset_name = (payload.get("dataset") or {}).get("name")
    models = run.get("selected_models") or []
    if run:
        abstract["purpose"] = (
            f"基于数据集「{dataset_name or '—'}」，针对{task_label}任务"
            f"构建并比较 {len(models)} 个预测模型。"
        )
    method_parts: list[str] = []
    if target_summary:
        n = target_summary.get("n_samples")
        k = target_summary.get("n_features")
        if n is not None:
            method_parts.append(f"纳入样本 {n} 例" + (f"、变量 {k} 个" if k is not None else ""))
    if models:
        method_parts.append(f"候选模型：{'、'.join(models)}")
    validation = payload.get("validation")
    if validation:
        method_parts.append(
            f"交叉验证 {validation.get('strategy')}（n_splits={validation.get('n_splits')}，"
            f"seed={validation.get('seed')}）"
        )
    if method_parts:
        abstract["methods"] = "；".join(method_parts) + "。"
    ranking = (comparison or {}).get("ranking") or []
    top1 = (((comparison or {}).get("recommendation") or {}).get("top") or [None])[0]
    if top1:
        abstract["results"] = (
            f"{len(ranking)} 个模型完成评估，推荐 {top1['model_key']}：{top1['reason']}。"
        )
    if conclusion_text:
        abstract["conclusion"] = conclusion_text
    return abstract


def build_report_context(payload: dict[str, Any]) -> dict[str, Any]:
    """装配报告上下文；payload 各字段缺失时对应章节标记「不适用」。"""
    run = payload.get("run") or {}
    comparison = payload.get("comparison")
    charts = (comparison or {}).get("charts") or []
    explain_charts = [c for c in charts if c.get("kind") in _EXPLAIN_KINDS]
    perf_charts = [c for c in charts if c.get("kind") not in _EXPLAIN_KINDS]

    target_summary = payload.get("target_summary")
    quality = payload.get("quality_report")
    steps = payload.get("preprocess_steps")
    table = payload.get("table")
    baseline_table = payload.get("baseline_table")
    diagnostics = payload.get("diagnostics")
    calibration = payload.get("calibration")
    # P3：数据体检摘要 / 单因素筛选 / 生存补充统计（worker 装配；缺省 → 模板不渲染）
    eda_summary = payload.get("eda_summary")
    screening = payload.get("screening")
    survival_analysis = payload.get("survival_analysis")

    # 图题（docs/10 §2.1）：全文统一编号（第 5 章先于第 6 章渲染），并注入说明文案
    for i, chart in enumerate([*perf_charts, *explain_charts], start=1):
        chart["fig_no"] = i
        chart["caption"] = caption_for(str(chart.get("kind") or ""))

    recommendation = (comparison or {}).get("recommendation") or {}
    top1 = (recommendation.get("top") or [None])[0]

    # T6.7：LLM 解读段落（worker 装配 payload 时按分功能开关生成；缺省 → 模板拼句兜底）
    llm_interp = payload.get("llm_interpretations") or {}

    statements = _interpretation_statements(explain_charts)
    # T6.3：回归诊断 / 分类校准结论进入临床解读（真实检验输出的结论文本）
    if diagnostics:
        paragraph = str(diagnostics.get("paragraph") or "").replace("**", "")
        for chunk in paragraph.split("\n\n"):
            if chunk and chunk != "模型诊断":
                statements.append(chunk)
        vif = diagnostics.get("vif") or {}
        if vif.get("conclusion"):
            statements.append(vif["conclusion"])
    if calibration:
        hl = calibration.get("hosmer_lemeshow") or {}
        if hl.get("conclusion"):
            statements.append(hl["conclusion"])
        threshold = calibration.get("optimal_threshold") or {}
        if threshold.get("interpretation"):
            statements.append(threshold["interpretation"])

    conclusion_text = None
    if comparison and top1:
        n_models = len(run.get("selected_models") or [])
        conclusion_text = (
            f"综合 {n_models} 个模型的{run.get('task_type', '')}任务比较，"
            f"推荐模型 {top1['model_key']}：{top1['reason']}。"
            "本结论仅基于本次数据的交叉验证结果，需结合临床背景解读。"
        )

    # T6.15②：完美指标红旗（EPV<10 且主指标≥0.99），触发后贯穿局限性/结论章
    red_flag = detect_perfect_metric_redflag(payload)

    sections = [
        _section(
            "overview",
            target_summary is not None,
            {
                **dict(target_summary or {}),
                # Table 1 变量概况（真实列画像；docs/10 §2 数据概况）
                "columns": (quality or {}).get("column_profiles") or [],
                # T6.3：基线特征表（分层 + 组间差异检验）
                "baseline_table": baseline_table,
                # P3：数据体检摘要（阶段 A 自动产出）与单因素筛选表
                "eda_summary": eda_summary,
                "screening": screening,
            },
        ),
        _section(
            "quality",
            quality is not None,
            {
                "status": (quality or {}).get("status"),
                "blockers": (quality or {}).get("blockers"),
                "warnings": (quality or {}).get("warnings"),
                "issues": (quality or {}).get("issues") or [],
                "transform_log": payload.get("transform_log") or [],
                # P1-11（§12）：缺失机制（MCAR/MAR/MNAR 启发式，缺体检 → None 不渲染）
                "missingness": payload.get("missingness"),
            },
        ),
        _section(
            "preprocessing",
            steps is not None,
            {
                "steps": [
                    {**s, "params_text": _humanize_params(s.get("params"))} for s in (steps or [])
                ]
            },
        ),
        _section(
            "methods",
            bool(run),
            {
                "task_type": run.get("task_type"),
                "selected_models": run.get("selected_models") or [],
                "validation": payload.get("validation"),
                "task_detection": payload.get("task_detection"),
            },
        ),
        _section(
            "performance",
            comparison is not None and table is not None,
            {
                "table": table or [],
                "charts": perf_charts,
                # T6.4：p 值列存在性（模板据此决定是否渲染 p 值列）
                "has_pvalues": any(r.get("p_value_text") for r in (table or [])),
                "significance_note": payload.get("significance_note"),
                # T6.3：回归诊断 / 分类校准（不适用任务类型 → None → 模板不渲染）
                "diagnostics": diagnostics,
                "calibration": calibration,
                # P3：生存专属补充（风险集人数表 + 中位风险分层 log-rank）
                "survival_analysis": survival_analysis,
                # T6.7：LLM 解读段落（None → 模板不渲染）
                "llm_paragraph": llm_interp.get("performance"),
                # T6.15③：指标三段式（含义/判读规则/本数据真实值），LLM 缺失时保可读底线
                "guides": build_performance_guides(
                    table,
                    ((comparison or {}).get("ranking") or [None])[0],
                    recommendation.get("primary_metric"),
                ),
            },
        ),
        _section(
            "comparison",
            comparison is not None,
            {
                "ranking": (comparison or {}).get("ranking") or [],
                "top": recommendation.get("top") or [],
                "not_recommended": recommendation.get("not_recommended") or [],
                "primary_metric": recommendation.get("primary_metric"),
                "formula": recommendation.get("formula"),
                "llm_paragraph": llm_interp.get("model_comparison"),
                "guide": build_comparison_guide(comparison, table),
            },
        ),
        _section(
            "explainability",
            bool(explain_charts),
            {"charts": explain_charts, "guides": build_explainability_guides(explain_charts)},
        ),
        _section(
            "clinical_interpretation",
            bool(statements) or bool(llm_interp.get("clinical_interpretation")),
            {
                "auto_generated": True,
                "notice": INTERPRETATION_NOTICE,
                "statements": statements,
                "llm_paragraph": llm_interp.get("clinical_interpretation"),
                "guides": build_clinical_guides(diagnostics, calibration, survival_analysis),
            },
        ),
        # P3：动态局限性（payload 真实统计触发）+ 静态基础条目
        # T6.15②：完美指标红旗触发时置顶局限性条目
        # P2-02（§51）：统计审查三段式（Major/Minor/Questions）附于局限性章末
        # P2-03（§52）：ML 审查（泄漏/过拟合/验证/校准/不均衡/可解释性）紧随其后
        _section(
            "limitations",
            True,
            {
                "items": (
                    [red_flag["limitation"], *build_limitations(payload)]
                    if red_flag
                    else build_limitations(payload)
                ),
                "review": review_methodology(payload),
                "ml_review": review_ml(payload),
            },
        ),
        # T6.11：TRIPOD/STROBE 自查（条目状态与依据全部由 payload 真实字段推导）
        _section("checklist", True, build_reporting_checklist(payload)),
        _section(
            "conclusion",
            conclusion_text is not None,
            # T6.15②：红旗触发时结论章强制醒目警示（推荐措辞降级，排名数值不变）
            {"text": conclusion_text or "", "red_flag": red_flag["warning"] if red_flag else None},
        ),
    ]

    return {
        "run": run,
        "dataset": payload.get("dataset") or {},
        "task_label": TASK_LABELS.get(str(run.get("task_type") or ""), ""),
        # P0-10（updateplan §69）：状态灯由确定性规则系统判定，不由 LLM 决定
        "analysis_status": compute_analysis_status(payload),
        "abstract": _build_abstract(payload, run, target_summary, comparison, conclusion_text),
        "sections": sections,
        "appendix": {
            "input_hash": payload.get("input_hash"),
            "preprocess_steps": steps or [],
            "validation": payload.get("validation"),
            "software": payload.get("software") or {},
            "disclaimer": DISCLAIMER,
        },
    }
