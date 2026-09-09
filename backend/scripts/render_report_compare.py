"""T6.15⑤ 整改前后报告对比渲染（一次性工具脚本，非产品代码）。

用复刻实据特征的合成 payload（分类、n=92、40 变量、EPV=0.7、AUC=1.0、
p 值 nan、中文预处理参数）分别渲染：
- before：git 历史 bcb656e 的旧模板（1.1.0，整改前）+ 新 context
  （context 改动只增不改，旧模板渲染行为与整改前一致）；
- after：当前模板（1.2.0）+ 新 context。

输出 report/report-before.html / report/report-after.html 供临床读者盲读终验。

用法（容器内）：python -m scripts.render_report_compare
"""

import json
from pathlib import Path

import jinja2
from app.engines.reporting.context import build_report_context
from app.engines.reporting.render import render_html

_OUT_DIR = Path(__file__).resolve().parents[2] / "report"
_OLD_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "report" / "_template_1.1.0.html.j2"
)


def _payload(p_value_text: str) -> dict:
    """复刻 report-434b9064.html 的实据特征（合成数值，仅用于渲染对比）。

    p_value_text：before 用 "nan"（整改前引擎产出），after 用 "—"
    （T6.15① statistics._compute_pvalue 的 nan 守卫已在引擎层拦截）。
    """
    return {
        "run": {
            "task_type": "classification",
            "status": "COMPLETED",
            "selected_models": ["logreg", "rf", "catboost"],
            "created_at": "2026-09-05 10:00:00",
            "finished_at": "2026-09-05 10:12:00",
        },
        "dataset": {"name": "住院患者结局数据集（脱敏合成副本）"},
        "target_summary": {
            "n_samples": 92,
            "n_features": 40,
            "positives": 28,
            "prevalence": 0.304,
        },
        "validation": {"strategy": "stratified_kfold", "n_splits": 5, "seed": 42},
        "quality_report": {
            "status": "PASSED_WITH_WARNINGS",
            "blockers": 0,
            "warnings": 2,
            "issues": [
                {
                    "severity": "warning",
                    "column": "bmi",
                    "message": "缺失率 12%",
                    "suggestion": "中位数填补",
                }
            ],
        },
        "transform_log": [{"action": "quick_fix", "column": "bmi", "affected_rows": 11}],
        "preprocess_steps": [
            {"type": "missing", "params": {"strategy": "中位数填补", "columns": ["bmi"]}},
            {"type": "scale", "params": {"method": "standard"}},
        ],
        "input_hash": "demo434b9064",
        "table": [
            {
                "model_key": "catboost",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 1.0, "std": 0.0}, "brier": {"mean": 0.02, "std": 0.0}},
                "p_value_text": "参考",
            },
            {
                "model_key": "rf",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 1.0, "std": 0.0}, "brier": {"mean": 0.03, "std": 0.01}},
                "p_value_text": p_value_text,
            },
            {
                "model_key": "logreg",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 1.0, "std": 0.0}, "brier": {"mean": 0.04, "std": 0.01}},
                "p_value_text": p_value_text,
            },
        ],
        "comparison": {
            "ranking": ["catboost", "rf", "logreg"],
            "recommendation": {
                "top": [
                    {
                        "model_key": "catboost",
                        "rank": 1,
                        "reason": "主指标最高（auc=1.0000±0.0000）",
                    }
                ],
                "not_recommended": [],
                "primary_metric": "auc",
                "formula": (
                    "score = 0.6×主指标归一化 + 0.2×稳定性归一化"
                    " + 0.2×次级指标归一化（docs/09 §4.1）"
                ),
            },
            "charts": [
                {"kind": "roc", "title": "ROC 曲线对比", "data": {"series": []}},
                {
                    "kind": "feature_importance",
                    "title": "特征重要性对比",
                    "data": {"features": ["出院诊断编码", "年龄", "住院天数"], "series": []},
                },
            ],
        },
        "screening": {
            "rows": [
                {
                    "feature": "出院诊断编码",
                    "test": "mannwhitney",
                    "effect": None,
                    "p_value": float("nan"),
                    "selected": False,
                }
            ],
            "alpha": 0.05,
            "selected_features": [],
            "n_total_tested": 40,
        },
        "software": {"python": "3.11", "scikit-learn": "1.5"},
    }


def main() -> None:
    if not _OLD_TEMPLATE.exists():
        raise SystemExit(f"缺少旧模板快照：{_OLD_TEMPLATE}（先 git show 导出）")
    before_ctx = build_report_context(_payload("nan"))
    after_ctx = build_report_context(_payload("—"))

    before_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_OLD_TEMPLATE.parent), autoescape=True
    )
    before = before_env.get_template(_OLD_TEMPLATE.name).render(collapsible=False, **before_ctx)
    after = render_html(after_ctx)

    _OUT_DIR.mkdir(exist_ok=True)
    (_OUT_DIR / "report-before.html").write_text(before, encoding="utf-8")
    (_OUT_DIR / "report-after.html").write_text(after, encoding="utf-8")
    summary = {
        "before": {
            "nan_cells": before.count("nan"),
            "empty_survival_fields": "事件数：；" in before,
            "red_flag_block": 'class="red-flag"' in before,
            "guide_blocks": before.count('class="guide"'),
            "escaped_unicode": "\\u4e2d" in before,
        },
        "after": {
            "nan_cells": after.count("nan"),
            "empty_survival_fields": "事件数：；" in after,
            "red_flag_block": 'class="red-flag"' in after,
            "guide_blocks": after.count('class="guide"'),
            "escaped_unicode": "\\u4e2d" in after,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
