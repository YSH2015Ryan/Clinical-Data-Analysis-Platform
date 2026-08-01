"""T7.2 Jinja2 中文模板测试（docs/10 §2、§5 DoD）。

- 免责声明与可复现附录强制存在；10 章节标题齐备；
- 缺数据章节显示「本次分析不适用」；数字与上下文一致（不虚构）；
- Table 1 变量概况来自真实列画像。
"""

from app.engines.reporting.context import SECTION_TITLES, build_report_context
from app.engines.reporting.render import render_html

from tests.test_report_context import _payload


def _render() -> str:
    return render_html(build_report_context(_payload()))


class TestTemplateMandatory:
    def test_disclaimer_present(self) -> None:
        html = _render()
        assert "本报告由 CDAP 自动生成，仅供科研参考，不构成临床诊断建议。" in html

    def test_reproducibility_appendix_present(self) -> None:
        html = _render()
        assert "附录：可复现性信息" in html
        assert "abc123" in html  # input_hash
        assert "scikit-learn" in html and "1.5" in html

    def test_all_section_titles(self) -> None:
        html = _render()
        for title in SECTION_TITLES.values():
            assert title in html

    def test_real_numbers_rendered(self) -> None:
        html = _render()
        assert "0.8700±0.0100" in html  # 性能表真实指标
        assert "主指标最高（auc=0.8700±0.0100）" in html  # 推荐理由
        assert "score = 0.6" in html  # 排名公式披露

    def test_interpretation_notice(self) -> None:
        html = _render()
        assert "需研究者核实" in html


class TestTable1:
    def test_column_profile_rows(self) -> None:
        payload = _payload()
        payload["quality_report"]["column_profiles"] = [
            {
                "name": "age",
                "inferred_type": "continuous",
                "missing_rate": 0.05,
                "unique": 47,
                "min": 18,
                "max": 89,
            }
        ]
        html = render_html(build_report_context(payload))
        assert "表 1 变量概况" in html
        assert "<td>age</td>" in html
        assert "5.0%" in html  # 缺失率


class TestNotApplicable:
    def test_missing_sections_show_note(self) -> None:
        payload = _payload()
        payload["quality_report"] = None
        payload["comparison"] = None
        html = render_html(build_report_context(payload))
        assert html.count("本次分析不适用") >= 4  # quality/performance/comparison/conclusion…
        assert "不构成临床诊断建议" in html  # 免责声明仍在

    def test_minimal_context_renders(self) -> None:
        ctx = build_report_context(
            {
                "run": {"task_type": "survival", "status": "FAILED", "selected_models": []},
                "dataset": {"name": "x"},
            }
        )
        html = render_html(ctx)
        assert "临床数据分析报告" in html
