"""T6.11 TRIPOD/STROBE 报告规范自查引擎测试（先行）。

自查条目的状态与依据必须由 payload 真实字段推导（红线8），不得凭空判定。
"""

from app.engines.reporting.checklist import build_reporting_checklist


def _full_payload() -> dict:
    """完整分类任务 payload（所有字段齐备 → 多数条目应满足）。"""
    return {
        "run": {"task_type": "classification", "selected_models": ["logreg", "rf"]},
        "target_summary": {
            "n_samples": 200,
            "n_features": 10,
            "n_classes": 2,
            "positives": 80,
            "prevalence": 0.4,
        },
        "validation": {"strategy": "stratified_kfold", "n_splits": 5, "seed": 42},
        "preprocess_steps": [{"type": "impute", "params": {"strategy": "median"}}],
        "table": [
            {
                "model_key": "logreg",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 0.85, "std": 0.03}},
            }
        ],
        "comparison": {
            "ranking": ["logreg", "rf"],
            "recommendation": {"top": [{"model_key": "logreg", "reason": "AUC 最高"}]},
            "charts": [{"kind": "roc", "data": {}}, {"kind": "calibration", "data": {}}],
        },
        "calibration": {"hosmer_lemeshow": {"p": 0.3}},
        "software": {"python": "3.11"},
        "input_hash": "abc123",
    }


class TestFullPayload:
    def test_all_items_have_real_evidence(self) -> None:
        result = build_reporting_checklist(_full_payload())
        assert result["items"]
        for item in result["items"]:
            assert item["status"] in {"满足", "部分满足", "待补充", "不适用"}
            assert item["item"] and item["evidence"]
        assert result["met"] <= result["total"] == len(result["items"])

    def test_sample_size_evidenced_with_real_n(self) -> None:
        result = build_reporting_checklist(_full_payload())
        item = next(i for i in result["items"] if "样本量" in i["item"])
        assert item["status"] == "满足"
        assert "200" in item["evidence"]

    def test_epv_computed_from_real_numbers(self) -> None:
        result = build_reporting_checklist(_full_payload())
        item = next(i for i in result["items"] if "EPV" in i["item"])
        # 阳性 80 / 特征 10 = 8.0 < 10 → 部分满足
        assert item["status"] == "部分满足"
        assert "80" in item["evidence"] and "10" in item["evidence"]

    def test_validation_and_seed_satisfied(self) -> None:
        result = build_reporting_checklist(_full_payload())
        item = next(i for i in result["items"] if "验证" in i["item"] and "内部" in i["item"])
        assert item["status"] == "满足"
        assert "42" in item["evidence"]

    def test_calibration_satisfied_when_present(self) -> None:
        result = build_reporting_checklist(_full_payload())
        item = next(i for i in result["items"] if "校准" in i["item"])
        assert item["status"] == "满足"


class TestMissingData:
    def test_no_calibration_pending(self) -> None:
        payload = _full_payload()
        payload["calibration"] = None
        result = build_reporting_checklist(payload)
        item = next(i for i in result["items"] if "校准" in i["item"])
        assert item["status"] == "待补充"

    def test_no_impute_step_flagged(self) -> None:
        payload = _full_payload()
        payload["preprocess_steps"] = [{"type": "scale", "params": {}}]
        result = build_reporting_checklist(payload)
        item = next(i for i in result["items"] if "缺失" in i["item"])
        assert item["status"] == "待补充"

    def test_minimal_payload_no_crash(self) -> None:
        result = build_reporting_checklist({"run": {"task_type": "regression"}})
        assert result["items"]
        assert result["met"] < result["total"]

    def test_survival_epv_uses_events(self) -> None:
        payload = _full_payload()
        payload["run"]["task_type"] = "survival"
        payload["target_summary"] = {"n_samples": 150, "n_features": 5, "events": 90}
        payload["calibration"] = None
        result = build_reporting_checklist(payload)
        item = next(i for i in result["items"] if "EPV" in i["item"])
        # 90 / 5 = 18 ≥ 10 → 满足
        assert item["status"] == "满足"
        assert "90" in item["evidence"]


class TestContract:
    def test_result_shape(self) -> None:
        result = build_reporting_checklist(_full_payload())
        assert set(result) >= {"standard", "items", "met", "total", "note"}
        assert "TRIPOD" in result["standard"]
        for item in result["items"]:
            assert set(item) == {"no", "item", "status", "evidence"}

    def test_items_sequentially_numbered(self) -> None:
        result = build_reporting_checklist(_full_payload())
        assert [i["no"] for i in result["items"]] == list(range(1, len(result["items"]) + 1))
