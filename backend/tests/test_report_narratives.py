"""T6.15③ 模板三段式加厚测试（路线图 T6.15 范围③；docs/10 §2）。

四章（模型性能/比较推荐/特征重要性/临床意义）每个指标给出
「含义 / 判读规则 / 本数据数值结论」三段；数字全部来自 payload
真实值（红线 8），LLM 缺失时报告仍达可读底线。
"""

from typing import Any

from app.engines.reporting.context import build_report_context
from app.engines.reporting.narratives import (
    build_clinical_guides,
    build_comparison_guide,
    build_explainability_guides,
    build_performance_guides,
)
from app.engines.reporting.render import render_html

from tests.test_report_context import _payload


def _table() -> list[dict[str, Any]]:
    return _payload()["table"]  # logreg auc=0.81±0.02, rf auc=0.87±0.01


class TestPerformanceGuides:
    def test_three_segments_with_real_numbers(self) -> None:
        guides = build_performance_guides(_table(), "rf", "auc")
        auc_guide = next(g for g in guides if g["metric"] == "auc")
        assert auc_guide["meaning"]  # 含义
        assert auc_guide["rule"]  # 判读规则
        assert "0.8700±0.0100" in auc_guide["reading"]  # 本数据真实值（Top1=rf）
        assert "rf" in auc_guide["reading"]

    def test_verdict_follows_rule_bands(self) -> None:
        guides = build_performance_guides(_table(), "rf", "auc")
        assert "良好" in next(g for g in guides if g["metric"] == "auc")["reading"]

    def test_unknown_metric_skipped(self) -> None:
        table = [
            {"model_key": "m1", "status": "SUCCESS", "metrics": {"foo": {"mean": 0.5, "std": 0.1}}}
        ]
        assert build_performance_guides(table, "m1", "foo") == []

    def test_stability_comment_from_real_std(self) -> None:
        table = [
            {
                "model_key": "m1",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 0.85, "std": 0.12}},
            }
        ]
        reading = build_performance_guides(table, "m1", "auc")[0]["reading"]
        assert "0.1200" in reading
        assert "波动" in reading  # std=0.12 折间波动提示

    def test_empty_table_no_crash(self) -> None:
        assert build_performance_guides([], None, "auc") == []


class TestComparisonGuide:
    def test_real_ranking_and_reason(self) -> None:
        payload = _payload()
        guide = build_comparison_guide(payload["comparison"], payload["table"])
        assert guide is not None
        assert guide["meaning"] and guide["rule"]
        assert "rf > logreg" in guide["reading"]  # 真实排名
        assert "主指标最高" in guide["reading"]  # 真实推荐理由

    def test_pvalue_text_quoted_when_present(self) -> None:
        payload = _payload()
        payload["table"][0]["p_value_text"] = "0.032*"
        guide = build_comparison_guide(payload["comparison"], payload["table"])
        assert "0.032*" in guide["reading"]

    def test_missing_comparison_none(self) -> None:
        assert build_comparison_guide(None, None) is None


class TestExplainabilityGuides:
    def test_feature_importance_guide_real_features(self) -> None:
        payload = _payload()
        charts = [
            c for c in payload["comparison"]["charts"] if c["kind"] == "feature_importance"
        ]
        guides = build_explainability_guides(charts)
        assert guides
        fi = guides[0]
        assert fi["meaning"] and fi["rule"]
        assert "age" in fi["reading"]  # 真实特征名
        assert "因果" in fi["rule"]  # 排序不等于因果的警示

    def test_empty_charts_no_guides(self) -> None:
        assert build_explainability_guides([]) == []


class TestClinicalGuides:
    def test_calibration_guide_real_conclusion(self) -> None:
        calibration = {
            "model_key": "rf",
            "hosmer_lemeshow": {
                "statistic": 3.2,
                "p_value": 0.78,
                "conclusion": "校准良好（p=0.78）",
            },
            "optimal_threshold": {"threshold": 0.4, "interpretation": "阈值 0.4 时约登指数最大"},
        }
        guides = build_clinical_guides(None, calibration, None)
        cal_guide = next(g for g in guides if "校准" in g["title"])
        assert cal_guide["meaning"] and cal_guide["rule"]
        assert "校准良好（p=0.78）" in cal_guide["reading"]  # 真实结论

    def test_diagnostics_guide_real_conclusion(self) -> None:
        diagnostics = {
            "model_key": "rf",
            "shapiro": {"conclusion": "残差近似正态（p=0.31）"},
            "breusch_pagan": {"conclusion": "未发现异方差（p=0.27）"},
        }
        guides = build_clinical_guides(diagnostics, None, None)
        diag = next(g for g in guides if "诊断" in g["title"])
        assert "残差近似正态（p=0.31）" in diag["reading"]

    def test_logrank_guide_real_values(self) -> None:
        survival = {
            "logrank": {"statistic": 4.56, "p_value": 0.033, "n_high": 46, "n_low": 46}
        }
        guides = build_clinical_guides(None, None, survival)
        lr = next(g for g in guides if "分层" in g["title"] or "log-rank" in g["title"].lower())
        assert "4.56" in lr["reading"] and "0.033" in lr["reading"]

    def test_all_absent_no_guides(self) -> None:
        assert build_clinical_guides(None, None, None) == []


class TestNarrativesInContextAndTemplate:
    def test_four_sections_carry_guides(self) -> None:
        ctx = build_report_context(_payload())
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        comp = next(s for s in ctx["sections"] if s["key"] == "comparison")
        explain = next(s for s in ctx["sections"] if s["key"] == "explainability")
        assert perf["data"]["guides"]  # 三段式块非空
        assert comp["data"]["guide"]
        assert explain["data"]["guides"]

    def test_three_segments_rendered_without_llm(self) -> None:
        """LLM 缺失（无 llm_interpretations）时三段式仍渲染——可读底线。"""
        html = render_html(build_report_context(_payload()))
        assert "含义：" in html and "判读规则：" in html and "本数据：" in html
        assert '<p class="llm-paragraph">' not in html  # 确认无 LLM 段落（元素级，非 CSS 定义）

    def test_clinical_guides_render_when_data_present(self) -> None:
        payload = _payload()
        payload["calibration"] = {
            "model_key": "rf",
            "hosmer_lemeshow": {
                "statistic": 3.2,
                "p_value": 0.78,
                "conclusion": "校准良好（p=0.78）",
            },
            "optimal_threshold": None,
        }
        html = render_html(build_report_context(payload))
        assert "校准良好（p=0.78）" in html
        assert "判读规则：" in html
