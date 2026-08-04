"""ReportContext 聚合器（docs/10 §2-3；docs/18 T7.1）。

纯函数：worker/service 装配好 payload（DB + 存储产物）后，本模块把它组织为
10 章节 + 附录的报告上下文。缺数据的章节标记 applicable=False（「本次分析不适用」），
不报错；免责声明与可复现附录强制存在（CLAUDE.md §8）。
"""

from typing import Any

from app.engines.reporting.captions import caption_for

DISCLAIMER = "本报告由 CDAP 自动生成，仅供科研参考，不构成临床诊断建议。"
NOT_APPLICABLE = "本次分析不适用"
INTERPRETATION_NOTICE = "本节内容由系统自动生成，仅供线索参考，需研究者核实后方可写入论文。"

SECTION_TITLES: dict[str, str] = {
    "overview": "1. 数据概况",
    "quality": "2. 数据质量",
    "preprocessing": "3. 预处理过程",
    "methods": "4. 分析方法",
    "performance": "5. 模型表现",
    "explainability": "6. 特征与可解释性",
    "comparison": "7. 模型比较与推荐",
    "clinical_interpretation": "8. 医学解释",
    "limitations": "9. 局限性",
    "conclusion": "10. 结论",
}

# 可解释性图表（归第 6 章），其余对比图表归第 5 章（docs/10 §2）
_EXPLAIN_KINDS = {"feature_importance", "hr_forest"}

_LIMITATIONS = [
    "本分析基于回顾性数据，可能存在选择偏倚与信息偏倚。",
    "数据来自单中心，结论外推到其他人群需谨慎。",
    "模型未进行外部验证，泛化性能未知。",
    "样本量有限时，交叉验证估计的方差可能较大。",
]


def _na() -> dict[str, Any]:
    return {"note": NOT_APPLICABLE}


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

    # 图题（docs/10 §2.1）：全文统一编号（第 5 章先于第 6 章渲染），并注入说明文案
    for i, chart in enumerate([*perf_charts, *explain_charts], start=1):
        chart["fig_no"] = i
        chart["caption"] = caption_for(str(chart.get("kind") or ""))

    recommendation = (comparison or {}).get("recommendation") or {}
    top1 = (recommendation.get("top") or [None])[0]

    statements = _interpretation_statements(explain_charts)

    conclusion_text = None
    if comparison and top1:
        n_models = len(run.get("selected_models") or [])
        conclusion_text = (
            f"综合 {n_models} 个模型的{run.get('task_type', '')}任务比较，"
            f"推荐模型 {top1['model_key']}：{top1['reason']}。"
            "本结论仅基于本次数据的交叉验证结果，需结合临床背景解读。"
        )

    sections = [
        _section(
            "overview",
            target_summary is not None,
            {
                **dict(target_summary or {}),
                # Table 1 变量概况（真实列画像；docs/10 §2 数据概况）
                "columns": (quality or {}).get("column_profiles") or [],
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
            },
        ),
        _section("preprocessing", steps is not None, {"steps": steps or []}),
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
            {"table": table or [], "charts": perf_charts},
        ),
        _section(
            "explainability",
            bool(explain_charts),
            {"charts": explain_charts},
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
            },
        ),
        _section(
            "clinical_interpretation",
            bool(statements),
            {
                "auto_generated": True,
                "notice": INTERPRETATION_NOTICE,
                "statements": statements,
            },
        ),
        _section("limitations", True, {"items": list(_LIMITATIONS)}),
        _section(
            "conclusion",
            conclusion_text is not None,
            {"text": conclusion_text or ""},
        ),
    ]

    return {
        "run": run,
        "dataset": payload.get("dataset") or {},
        "sections": sections,
        "appendix": {
            "input_hash": payload.get("input_hash"),
            "preprocess_steps": steps or [],
            "validation": payload.get("validation"),
            "software": payload.get("software") or {},
            "disclaimer": DISCLAIMER,
        },
    }
