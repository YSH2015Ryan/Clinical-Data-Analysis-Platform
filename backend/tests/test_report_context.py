"""T7.1 ReportContext 聚合器单测（docs/10 §2-3）。

- 10 章节 + 附录齐备；缺数据章节标记「不适用」而非报错；
- 免责声明与可复现附录强制存在；结论只引用真实指标值。
"""

from app.engines.reporting.captions import FIGURE_CAPTIONS
from app.engines.reporting.context import SECTION_TITLES, build_report_context


def _payload() -> dict:
    return {
        "run": {
            "task_type": "classification",
            "status": "COMPLETED",
            "selected_models": ["logreg", "rf"],
            "created_at": "2026-07-31 10:00:00",
            "finished_at": "2026-07-31 10:05:00",
        },
        "dataset": {"name": "示例数据集"},
        "target_summary": {"n_samples": 200, "n_features": 8, "positives": 96, "prevalence": 0.48},
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
        "transform_log": [{"action": "quick_fix", "column": "bmi", "affected_rows": 24}],
        "preprocess_steps": [
            {"type": "missing", "params": {"default": "median"}},
            {"type": "scale", "params": {"method": "standard"}},
        ],
        "input_hash": "abc123",
        "table": [
            {
                "model_key": "logreg",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 0.81, "std": 0.02}},
            },
            {
                "model_key": "rf",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 0.87, "std": 0.01}},
            },
        ],
        "comparison": {
            "ranking": ["rf", "logreg"],
            "recommendation": {
                "top": [
                    {"model_key": "rf", "rank": 1, "reason": "主指标最高（auc=0.8700±0.0100）"}
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
                    "data": {"features": ["age"], "series": []},
                },
            ],
        },
        "software": {"python": "3.11", "scikit-learn": "1.5"},
    }


class TestSections:
    def test_all_sections_present(self) -> None:
        ctx = build_report_context(_payload())
        assert [s["key"] for s in ctx["sections"]] == list(SECTION_TITLES)
        for s in ctx["sections"]:
            assert s["title"]
            assert isinstance(s["applicable"], bool)

    def test_overview_numbers(self) -> None:
        ctx = build_report_context(_payload())
        overview = ctx["sections"][0]["data"]
        assert overview["n_samples"] == 200
        assert overview["prevalence"] == 0.48

    def test_performance_and_comparison_real_values(self) -> None:
        ctx = build_report_context(_payload())
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        assert perf["data"]["table"][0]["metrics"]["auc"]["mean"] == 0.81
        comp = next(s for s in ctx["sections"] if s["key"] == "comparison")
        assert comp["data"]["ranking"] == ["rf", "logreg"]
        assert "score = 0.6" in comp["data"]["formula"]
        conclusion = next(s for s in ctx["sections"] if s["key"] == "conclusion")
        assert "rf" in conclusion["data"]["text"] and "0.8700" in conclusion["data"]["text"]

    def test_explainability_chart_kinds_split(self) -> None:
        ctx = build_report_context(_payload())
        explain = next(s for s in ctx["sections"] if s["key"] == "explainability")
        assert [c["kind"] for c in explain["data"]["charts"]] == ["feature_importance"]
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        assert [c["kind"] for c in perf["data"]["charts"]] == ["roc"]

    def test_checklist_section_present_with_real_items(self) -> None:
        """T6.11：TRIPOD 自查章节恒在，条目状态由 payload 真实字段推导。"""
        ctx = build_report_context(_payload())
        checklist = next(s for s in ctx["sections"] if s["key"] == "checklist")
        assert checklist["applicable"] is True
        data = checklist["data"]
        assert "TRIPOD" in data["standard"]
        assert data["total"] == len(data["items"]) > 0
        # 结论章节在自查之后（期刊结构：局限 → 自查 → 结论）
        keys = [s["key"] for s in ctx["sections"]]
        assert keys.index("checklist") > keys.index("limitations")
        assert keys.index("checklist") < keys.index("conclusion")


class TestFigureCaptions:
    """docs/10 §2.1：每图必带全文统一编号 + 说明文案。"""

    def test_fig_no_globally_numbered(self) -> None:
        ctx = build_report_context(_payload())
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        explain = next(s for s in ctx["sections"] if s["key"] == "explainability")
        # 第 5 章图先于第 6 章编号
        assert perf["data"]["charts"][0]["fig_no"] == 1
        assert explain["data"]["charts"][0]["fig_no"] == 2

    def test_caption_injected_for_known_kind(self) -> None:
        ctx = build_report_context(_payload())
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        caption = perf["data"]["charts"][0]["caption"]
        assert "AUC" in caption and "随机" in caption  # roc 说明要点

    def test_unknown_kind_empty_caption_not_crash(self) -> None:
        payload = _payload()
        payload["comparison"]["charts"] = [{"kind": "unknown_x", "title": "t", "data": {}}]
        ctx = build_report_context(payload)
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        assert perf["data"]["charts"][0]["caption"] == ""

    def test_captions_cover_all_produced_kinds(self) -> None:
        """charts.py 实际产出的 kind 必须全部有说明文案（防新增图漏写说明）。"""
        produced = {
            "roc",
            "calibration",
            "dca",
            "confusion_matrix",
            "km",
            "cindex_forest",
            "prediction_scatter",
            "feature_importance",
            "hr_forest",
        }
        missing = produced - set(FIGURE_CAPTIONS)
        assert not missing, f"缺少图题说明: {missing}"
        assert all(FIGURE_CAPTIONS[k] for k in produced)

    def test_clinical_interpretation_marked_auto(self) -> None:
        ctx = build_report_context(_payload())
        interp = next(s for s in ctx["sections"] if s["key"] == "clinical_interpretation")
        assert interp["data"]["auto_generated"] is True
        assert "核实" in interp["data"]["notice"]

    def test_appendix_mandatory(self) -> None:
        ctx = build_report_context(_payload())
        appendix = ctx["appendix"]
        assert appendix["input_hash"] == "abc123"
        assert appendix["software"]["scikit-learn"] == "1.5"
        assert "不构成临床诊断建议" in appendix["disclaimer"]


class TestLlmInterpretations:
    """T6.7：LLM 解读段落经 payload 注入对应章节；缺省时章节结构不变（模板拼句兜底）。"""

    def test_llm_paragraphs_injected_into_sections(self) -> None:
        payload = _payload()
        payload["llm_interpretations"] = {
            "model_comparison": "配对检验显示 rf 显著优于 logreg。",
            "performance": "各模型交叉验证性能整体稳定。",
            "clinical_interpretation": "重要特征具有明确临床意义。",
        }
        ctx = build_report_context(payload)
        perf = next(s for s in ctx["sections"] if s["key"] == "performance")
        comp = next(s for s in ctx["sections"] if s["key"] == "comparison")
        interp = next(s for s in ctx["sections"] if s["key"] == "clinical_interpretation")
        assert perf["data"]["llm_paragraph"] == "各模型交叉验证性能整体稳定。"
        assert comp["data"]["llm_paragraph"] == "配对检验显示 rf 显著优于 logreg。"
        assert interp["data"]["llm_paragraph"] == "重要特征具有明确临床意义。"

    def test_absent_llm_interpretations_no_keys(self) -> None:
        ctx = build_report_context(_payload())
        for key in ("performance", "comparison", "clinical_interpretation"):
            section = next(s for s in ctx["sections"] if s["key"] == key)
            assert not section["data"].get("llm_paragraph")

    def test_llm_paragraph_marks_section_applicable_without_statements(self) -> None:
        """无模板语句（无诊断/校准/可解释产物）但有 LLM 段落时，临床解读章节仍适用。"""
        payload = _payload()
        payload["comparison"]["charts"] = [
            {"kind": "roc", "title": "ROC 曲线对比", "data": {"series": []}}
        ]
        payload["llm_interpretations"] = {"clinical_interpretation": "基于真实指标的解读。"}
        ctx = build_report_context(payload)
        interp = next(s for s in ctx["sections"] if s["key"] == "clinical_interpretation")
        assert interp["applicable"] is True
        assert interp["data"]["llm_paragraph"] == "基于真实指标的解读。"
        assert interp["data"]["statements"] == []


class TestMissingData:
    def test_missing_quality_report_not_applicable(self) -> None:
        payload = _payload()
        payload["quality_report"] = None
        ctx = build_report_context(payload)
        quality = next(s for s in ctx["sections"] if s["key"] == "quality")
        assert quality["applicable"] is False
        assert quality["data"]["note"] == "本次分析不适用"

    def test_missing_comparison(self) -> None:
        payload = _payload()
        payload["comparison"] = None
        ctx = build_report_context(payload)
        for key in ("performance", "comparison", "conclusion", "explainability"):
            section = next(s for s in ctx["sections"] if s["key"] == key)
            assert section["applicable"] is False
        appendix = ctx["appendix"]  # 附录仍然强制存在
        assert "不构成临床诊断建议" in appendix["disclaimer"]

    def test_missing_preprocess_snapshot(self) -> None:
        payload = _payload()
        payload["preprocess_steps"] = None
        payload["input_hash"] = None
        ctx = build_report_context(payload)
        prep = next(s for s in ctx["sections"] if s["key"] == "preprocessing")
        assert prep["applicable"] is False
        assert ctx["appendix"]["input_hash"] is None

    def test_minimal_payload_no_crash(self) -> None:
        ctx = build_report_context(
            {
                "run": {"task_type": "survival", "status": "FAILED", "selected_models": []},
                "dataset": {"name": "x"},
            }
        )
        assert len(ctx["sections"]) == len(SECTION_TITLES)
        assert all(
            s["applicable"] or s["data"].get("note") == "本次分析不适用" for s in ctx["sections"]
        )


class TestAbstract:
    """docs/10 §2 卷首结构化摘要：四要素全部由真实计算值填充，缺失则省略。"""

    def test_abstract_from_real_values(self) -> None:
        ctx = build_report_context(_payload())
        abstract = ctx["abstract"]
        assert "示例数据集" in abstract["purpose"]
        assert "分类 / 风险预测" in abstract["purpose"]
        assert "200 例" in abstract["methods"]
        assert "stratified_kfold" in abstract["methods"]
        assert "推荐 rf：主指标最高" in abstract["results"]
        assert "0.8700" in abstract["conclusion"]

    def test_abstract_minimal_payload_omits_missing(self) -> None:
        ctx = build_report_context(
            {"run": {"task_type": "survival", "selected_models": []}, "dataset": {"name": "x"}}
        )
        abstract = ctx["abstract"]
        assert "生存分析" in abstract["purpose"]
        assert "methods" not in abstract  # 无数据 → 省略，不虚构
        assert "results" not in abstract and "conclusion" not in abstract


class TestSupplementPlanLimitations:
    """T6.14 接入:报告动态局限性消费体检 supplement_plan(同一事实源)。

    只并入运行级动态条目未覆盖的类型(variable_roles/power);
    epv/imbalance/survival_events 已由运行级条目覆盖(口径=建模数据,
    更贴近报告对象),不重复列入。
    """

    def _plan(self) -> dict:
        return {
            "items": [
                {
                    "deficit_type": "epv",
                    "current": {},
                    "target": {},
                    "gap": {},
                    "suggestion": "体检口径的 EPV 建议(不应出现在报告局限性)",
                    "basis": "b",
                },
                {
                    "deficit_type": "variable_roles",
                    "current": {},
                    "target": {},
                    "gap": {"missing_roles": ["性别"]},
                    "suggestion": "缺少变量角色:性别,建议补充采集",
                    "basis": "b",
                },
                {
                    "deficit_type": "power",
                    "current": {},
                    "target": {},
                    "gap": {},
                    "suggestion": "小效应下把握度仅 0.12,需每组 394 例",
                    "basis": "b",
                },
            ],
            "overall": "o",
        }

    def test_uncovered_types_appended_epv_not_duplicated(self) -> None:
        from app.engines.reporting.limitations import build_limitations

        payload = _payload()
        payload["supplement_plan"] = self._plan()
        items = build_limitations(payload)
        assert any("缺少变量角色:性别" in i for i in items)
        assert any("每组 394 例" in i for i in items)
        # 体检口径 EPV 建议不重复(运行级动态条目已覆盖该类型)
        assert not any("体检口径的 EPV 建议" in i for i in items)

    def test_no_supplement_plan_unchanged(self) -> None:
        from app.engines.reporting.limitations import build_limitations

        before = build_limitations(_payload())
        payload = _payload()
        payload["supplement_plan"] = None
        assert build_limitations(payload) == before
