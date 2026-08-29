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


class TestFigureCaptions:
    """docs/10 §2.1：图下输出编号图题 + 说明段落。"""

    def test_caption_paragraphs_rendered(self) -> None:
        html = _render()
        assert '<p class="fig-caption">' in html
        assert "图 1" in html and "图 2" in html  # 全文统一编号
        assert "ROC 曲线对比。" in html  # 图题标题

    def test_caption_explanation_text(self) -> None:
        html = _render()
        assert "相当于随机猜测" in html  # roc 说明内容（读法+意义）

    def test_academic_typography(self) -> None:
        html = _render()
        assert "@page" in html  # 页码规则
        assert "Noto Serif CJK SC" in html  # 正文衬线
        assert "#1677ff" not in html  # 商务深色，不再用主题蓝


class TestJournalLayout:
    """docs/10 §2 卷首与期刊排版（2026-08-10 修订：IMRaD + TRIPOD 顺序）。"""

    def test_structured_abstract(self) -> None:
        html = _render()
        assert "摘　要" in html
        assert "目的：" in html and "方法：" in html
        assert "结果：" in html and "结论：" in html
        assert "示例数据集" in html  # 目的含真实数据集名
        assert "推荐 rf：主指标最高" in html  # 结果引用真实 Top1

    def test_page_header_footer(self) -> None:
        html = _render()
        assert "@top-center" in html  # 页眉短标题
        assert "counter(pages)" in html  # 页脚「第 X 页 / 共 Y 页」
        assert "@page :first" in html  # 首页无页眉

    def test_table_captions_numbered(self) -> None:
        """每表必带表题（表上），全文连续编号；_payload 无列画像 → 首表为质量清单。"""
        html = _render()
        assert "表 1 数据质量问题清单" in html
        assert "表 4 模型性能比较" in html
        # T6.11：自查表插入结论前 → 附录表顺延
        assert "表 5 报告规范自查" in html
        assert "表 7 软件版本" in html

    def test_imrad_part_dividers(self) -> None:
        html = _render()
        assert "研 究 方 法" in html and "研 究 结 果" in html and "讨　　论" in html


class TestCollapsible:
    """docs/10 §2.2：仅 HTML 产物重点表默认折叠；派生格式全展开。"""

    def test_collapsible_details(self) -> None:
        html = render_html(build_report_context(_payload()), collapsible=True)
        assert '<details class="fold">' in html
        assert "<summary>表 1 数据质量问题清单</summary>" in html
        assert "<caption>" not in html  # 折叠模式无 caption 重复

    def test_default_not_collapsible(self) -> None:
        html = _render()
        assert "<details" not in html
        assert "<caption>表 1 数据质量问题清单</caption>" in html
