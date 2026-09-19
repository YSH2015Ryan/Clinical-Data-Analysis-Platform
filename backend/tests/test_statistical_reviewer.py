"""§51 Statistical Reviewer（P2-02）——规则保底的统计方法学自动审查。

审查维度（§51）：Sample size / Missing data / Duplicate data / Variable selection /
Statistical method / Multiple comparisons / Validation strategy。
输出三段：Major Concerns / Minor Concerns / Questions for Researchers。
全部数值引用报告 payload 真实计算字段（红线 8）；规则确定性、可复现；
LLM 表达增强预留 llm_summary 槽位（本模块不调用 LLM）。
"""

from typing import Any

import pytest

from app.engines.reporting.statistical_reviewer import review_methodology


def _payload(**over: Any) -> dict[str, Any]:
    """模拟 assemble_report_payload 的最小可用 payload；over 覆盖顶层键。"""
    base: dict[str, Any] = {
        "run": {
            "task_type": "classification",
            "status": "SUCCEEDED",
            "selected_models": ["logistic", "xgboost"],
            "exploratory_mode": False,
        },
        "target_summary": {
            "n_samples": 500,
            "n_features": 8,
            "prevalence": 0.3,
            "positives": 150,
        },
        "validation": {"strategy": "stratified_kfold", "n_splits": 5, "seed": 42},
        "quality_report": {
            "status": "PASSED",
            "issues": [],
            "column_profiles": [
                {"name": "age", "missing_rate": 0.0, "inferred_type": "continuous"},
                {"name": "bmi", "missing_rate": 0.0, "inferred_type": "continuous"},
            ],
        },
        "transform_log": [],
        "preprocess_steps": [{"type": "missing", "params": {"default": "median"}}],
        "screening": None,
        "missingness": {"variables": [], "has_outcome_associated_missingness": False},
        "comparison": {
            "ranking": ["xgboost", "logistic"],
            "recommendation": {"primary_metric": "auc"},
        },
        "table": [
            {"model_key": "xgboost", "metrics": {"auc": {"mean": 0.85}}},
            {"model_key": "logistic", "metrics": {"auc": {"mean": 0.8}}, "p_value_text": "0.03"},
        ],
        "diagnostics": None,
        "calibration": {"hosmer_lemeshow": {"conclusion": "校准可接受"}},
    }
    base.update(over)
    return base


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {i["id"] for i in items}


class TestContract:
    def test_output_keys(self) -> None:
        result = review_methodology(_payload())
        assert set(result) >= {"major_concerns", "minor_concerns", "questions"}
        assert result["llm_summary"] is None  # 规则保底；LLM 槽位预留

    def test_item_shape(self) -> None:
        result = review_methodology(
            _payload(target_summary={"n_samples": 100, "n_features": 8, "positives": 20})
        )
        for item in result["major_concerns"] + result["minor_concerns"]:
            assert item["id"] and item["dimension"] and item["text"] and item["basis"]
        for q in result["questions"]:
            assert q["id"] and q["text"]

    def test_deterministic(self) -> None:
        payload = _payload()
        assert review_methodology(payload) == review_methodology(payload)


class TestCleanAnalysis:
    def test_no_major_concern(self) -> None:
        result = review_methodology(_payload())
        assert result["major_concerns"] == []

    def test_external_validation_question_always(self) -> None:
        result = review_methodology(_payload())
        assert "SRQ-EXTERNAL" in _ids(result["questions"])


class TestSampleSize:
    def test_epv_below_10_major(self) -> None:
        """150 阳性 / 20 特征 = EPV 7.5 < 10 → Major。"""
        result = review_methodology(
            _payload(target_summary={"n_samples": 500, "n_features": 20, "positives": 150})
        )
        epv = [c for c in result["major_concerns"] if c["id"] == "SR-EPV"]
        assert epv and epv[0]["dimension"] == "sample_size"
        assert "7.5" in epv[0]["basis"]  # 真实计算值写入依据串

    def test_survival_epv_uses_events(self) -> None:
        result = review_methodology(
            _payload(
                run={
                    "task_type": "survival",
                    "selected_models": ["coxph", "rsf"],
                    "exploratory_mode": False,
                },
                target_summary={"n_samples": 300, "n_features": 10, "events": 50},
            )
        )
        assert "SR-EPV" in _ids(result["major_concerns"])  # 50/10=5<10

    def test_small_sample_minor(self) -> None:
        result = review_methodology(
            _payload(target_summary={"n_samples": 150, "n_features": 5, "positives": 60})
        )
        assert "SR-SMALL-N" in _ids(result["minor_concerns"])

    def test_regression_low_samples_per_feature_minor(self) -> None:
        result = review_methodology(
            _payload(
                run={
                    "task_type": "regression",
                    "selected_models": ["ridge", "lasso"],
                    "exploratory_mode": False,
                },
                target_summary={"n_samples": 60, "n_features": 10},
            )
        )
        assert "SR-REG-NP" in _ids(result["minor_concerns"])


class TestMissingData:
    def test_high_missing_minor(self) -> None:
        profiles = [
            {"name": "age", "missing_rate": 0.0, "inferred_type": "continuous"},
            {"name": "crp", "missing_rate": 0.25, "inferred_type": "continuous"},
        ]
        result = review_methodology(
            _payload(quality_report={"status": "PASSED", "issues": [], "column_profiles": profiles})
        )
        item = [c for c in result["minor_concerns"] if c["id"] == "SR-MISS-HIGH"]
        assert item and "crp" in item[0]["basis"] and item[0]["dimension"] == "missing_data"

    def test_possible_mnar_minor(self) -> None:
        result = review_methodology(
            _payload(missingness={"variables": [], "has_outcome_associated_missingness": True})
        )
        assert "SR-MNAR" in _ids(result["minor_concerns"])

    def test_missing_mechanism_not_assessed_question(self) -> None:
        profiles = [{"name": "crp", "missing_rate": 0.1, "inferred_type": "continuous"}]
        result = review_methodology(
            _payload(
                quality_report={"status": "PASSED", "issues": [], "column_profiles": profiles},
                missingness=None,
            )
        )
        assert "SRQ-MISSING-MECH" in _ids(result["questions"])

    def test_no_missing_no_question(self) -> None:
        """无缺失列时不问缺失机制。"""
        result = review_methodology(_payload(missingness=None))
        assert "SRQ-MISSING-MECH" not in _ids(result["questions"])


class TestDuplicateData:
    def test_rv401_major(self) -> None:
        issues = [
            {
                "rule_id": "RV401",
                "severity": "warning",
                "message": "发现 12 行完全重复，可在线去重",
                "affected_rows": 12,
            }
        ]
        result = review_methodology(
            _payload(quality_report={"status": "PASSED_WITH_WARNINGS", "issues": issues,
                                     "column_profiles": []})
        )
        item = [c for c in result["major_concerns"] if c["id"] == "SR-DUP"]
        assert item and item[0]["dimension"] == "duplicate_data" and "12" in item[0]["basis"]


class TestVariableSelection:
    def test_wide_minor(self) -> None:
        """n_features > n_samples/10 → 特征相对样本偏多。"""
        result = review_methodology(
            _payload(target_summary={"n_samples": 100, "n_features": 15, "positives": 60})
        )
        assert "SR-WIDE" in _ids(result["minor_concerns"])

    def test_screening_selection_bias_question(self) -> None:
        result = review_methodology(
            _payload(screening={"correction": "bh", "n_tests": 20, "rows": []})
        )
        assert "SRQ-SCREENING" in _ids(result["questions"])


class TestStatisticalMethod:
    def test_single_model_minor(self) -> None:
        result = review_methodology(
            _payload(run={"task_type": "classification", "selected_models": ["logistic"],
                          "exploratory_mode": False})
        )
        assert "SR-SINGLE-MODEL" in _ids(result["minor_concerns"])

    def test_regression_without_diagnostics_question(self) -> None:
        result = review_methodology(
            _payload(
                run={"task_type": "regression", "selected_models": ["ridge", "lasso"],
                     "exploratory_mode": False},
                diagnostics=None,
            )
        )
        assert "SRQ-DIAG" in _ids(result["questions"])

    def test_classification_without_calibration_question(self) -> None:
        result = review_methodology(_payload(calibration=None))
        assert "SRQ-CALIB" in _ids(result["questions"])


class TestMultipleComparisons:
    def test_screening_none_correction_major(self) -> None:
        result = review_methodology(
            _payload(screening={"correction": "none", "n_tests": 30, "rows": []})
        )
        item = [c for c in result["major_concerns"] if c["id"] == "SR-MC-NONE"]
        assert item and item[0]["dimension"] == "multiple_comparisons" and "30" in item[0]["basis"]

    def test_screening_bh_no_major(self) -> None:
        result = review_methodology(
            _payload(screening={"correction": "bh", "n_tests": 30, "rows": []})
        )
        assert "SR-MC-NONE" not in _ids(result["major_concerns"])

    def test_unadjusted_pairwise_minor(self) -> None:
        """≥3 个模型且性能表含两两 t 检验 p 值（未校正）→ Minor。"""
        table = [
            {"model_key": "a", "metrics": {"auc": {"mean": 0.9}}},
            {"model_key": "b", "metrics": {"auc": {"mean": 0.8}}, "p_value_text": "0.04"},
            {"model_key": "c", "metrics": {"auc": {"mean": 0.7}}, "p_value_text": "0.01"},
        ]
        result = review_methodology(
            _payload(
                run={"task_type": "classification", "selected_models": ["a", "b", "c"],
                     "exploratory_mode": False},
                table=table,
                comparison={"ranking": ["a", "b", "c"], "recommendation": {"primary_metric": "auc"}},
            )
        )
        assert "SR-MC-PAIRWISE" in _ids(result["minor_concerns"])


class TestValidationStrategy:
    def test_few_folds_minor(self) -> None:
        result = review_methodology(
            _payload(validation={"strategy": "kfold", "n_splits": 3, "seed": 42})
        )
        assert "SR-CV-FOLDS" in _ids(result["minor_concerns"])

    def test_temporal_question(self) -> None:
        profiles = [{"name": "admission_date", "missing_rate": 0.0, "inferred_type": "datetime"}]
        result = review_methodology(
            _payload(
                quality_report={"status": "PASSED", "issues": [], "column_profiles": profiles},
                validation={"strategy": "kfold", "n_splits": 5, "seed": 42},
            )
        )
        assert "SRQ-TEMPORAL" in _ids(result["questions"])

    def test_perfect_metric_major(self) -> None:
        """T6.15 红旗（EPV<10 且主指标≥0.99）→ Major Concern。"""
        result = review_methodology(
            _payload(
                target_summary={"n_samples": 200, "n_features": 20, "positives": 100},
                comparison={
                    "ranking": ["xgboost"],
                    "recommendation": {"primary_metric": "auc"},
                    "charts": [],
                },
                table=[{"model_key": "xgboost", "metrics": {"auc": {"mean": 0.999}}}],
            )
        )
        assert "SR-PERFECT" in _ids(result["major_concerns"])


class TestEmptyPayload:
    def test_empty_payload_no_crash(self) -> None:
        """payload 大量缺失（早期失败运行）→ 不报错，至少保留外部验证问题。"""
        result = review_methodology({})
        assert isinstance(result["major_concerns"], list)
        assert "SRQ-EXTERNAL" in _ids(result["questions"])
