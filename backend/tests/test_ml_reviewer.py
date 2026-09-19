"""§52 ML Reviewer（P2-03）——规则保底的机器学习审查。

审查维度（§52）：Leakage / Overfitting / Validation / Calibration /
Class imbalance / Feature importance。输出与 §51 同构的三段式
（major_concerns / minor_concerns / questions），数值全部引用 payload
真实计算字段（红线 8），规则确定性、可复现。

与 §51 统计审查的分工：EPV/小样本/筛选校正等统计学问题归
statistical_reviewer；本模块只覆盖 ML 工程视角（泄漏门禁、折间方差、
验证配置缺失、校准度、类别不均衡、可解释性），不重复报 SR-PERFECT
（红旗由统计审查 SR-PERFECT 统一呈现）。
"""

from typing import Any

from app.engines.reporting.ml_reviewer import review_ml


def _payload(**over: Any) -> dict[str, Any]:
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
        "integrity": {"findings": []},
        "comparison": {
            "ranking": ["xgboost", "logistic"],
            "recommendation": {"primary_metric": "auc"},
            "charts": [
                {
                    "kind": "feature_importance",
                    "data": {
                        "features": ["age", "bmi"],
                        "series": [
                            {"model_key": "xgboost", "values": [1.0, 0.8]},
                            {"model_key": "logistic", "values": [1.0, 0.7]},
                        ],
                    },
                }
            ],
        },
        "table": [
            {"model_key": "xgboost", "metrics": {"auc": {"mean": 0.85, "std": 0.02}}},
            {"model_key": "logistic", "metrics": {"auc": {"mean": 0.8, "std": 0.03}}},
        ],
        "calibration": {"hosmer_lemeshow": {"p_value": 0.4, "conclusion": "校准可接受"}},
    }
    base.update(over)
    return base


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {i["id"] for i in items}


class TestContract:
    def test_output_keys_and_llm_slot(self) -> None:
        result = review_ml(_payload())
        assert set(result) >= {"major_concerns", "minor_concerns", "questions"}
        assert result["llm_summary"] is None

    def test_item_shape(self) -> None:
        result = review_ml(_payload(validation=None))
        for item in result["major_concerns"] + result["minor_concerns"]:
            assert item["id"] and item["dimension"] and item["text"] and item["basis"]
        for q in result["questions"]:
            assert q["id"] and q["text"]

    def test_deterministic(self) -> None:
        payload = _payload()
        assert review_ml(payload) == review_ml(payload)

    def test_clean_payload_no_major(self) -> None:
        result = review_ml(_payload())
        assert result["major_concerns"] == []


class TestLeakage:
    def test_blocker_finding_major(self) -> None:
        integrity = {
            "findings": [
                {
                    "severity": "blocker",
                    "rule": "TARGET_PROXY",
                    "message": "leak_copy 与结局 corr=1.0",
                }
            ]
        }
        result = review_ml(_payload(integrity=integrity))
        item = [c for c in result["major_concerns"] if c["id"] == "MLR-LEAKAGE-BLOCKER"]
        assert item and item[0]["dimension"] == "leakage" and "leak_copy" in item[0]["basis"]

    def test_warning_finding_minor(self) -> None:
        integrity = {
            "findings": [
                {"severity": "warning", "rule": "NEAR_ID", "message": "patient_no 近似唯一标识"}
            ]
        }
        result = review_ml(_payload(integrity=integrity))
        assert "MLR-LEAKAGE-WARN" in _ids(result["minor_concerns"])
        assert "MLR-LEAKAGE-BLOCKER" not in _ids(result["major_concerns"])


class TestOverfitting:
    def test_high_fold_variance_minor(self) -> None:
        """Top1 主指标折间 std/mean > 0.10 → 稳定性不足。"""
        result = review_ml(
            _payload(
                table=[
                    {"model_key": "xgboost", "metrics": {"auc": {"mean": 0.80, "std": 0.12}}},
                    {"model_key": "logistic", "metrics": {"auc": {"mean": 0.78, "std": 0.03}}},
                ]
            )
        )
        item = [c for c in result["minor_concerns"] if c["id"] == "MLR-FOLD-VAR"]
        assert item and item[0]["dimension"] == "overfitting"
        assert "0.12" in item[0]["basis"] and "0.8" in item[0]["basis"]

    def test_stable_folds_no_concern(self) -> None:
        result = review_ml(_payload())
        assert "MLR-FOLD-VAR" not in _ids(result["minor_concerns"])


class TestValidation:
    def test_missing_validation_config_major(self) -> None:
        result = review_ml(_payload(validation=None))
        item = [c for c in result["major_concerns"] if c["id"] == "MLR-NO-VALIDATION"]
        assert item and item[0]["dimension"] == "validation"


class TestCalibration:
    def test_hl_reject_minor(self) -> None:
        result = review_ml(
            _payload(calibration={"hosmer_lemeshow": {"p_value": 0.01, "conclusion": "校准不足"}})
        )
        item = [c for c in result["minor_concerns"] if c["id"] == "MLR-HL"]
        assert item and item[0]["dimension"] == "calibration" and "0.01" in item[0]["basis"]

    def test_slope_far_from_one_minor(self) -> None:
        table = [
            {
                "model_key": "xgboost",
                "metrics": {
                    "auc": {"mean": 0.85, "std": 0.02},
                    "calibration_slope": {"mean": 0.5, "std": 0.05},
                },
            },
            {"model_key": "logistic", "metrics": {"auc": {"mean": 0.8, "std": 0.03}}},
        ]
        result = review_ml(_payload(table=table))
        item = [c for c in result["minor_concerns"] if c["id"] == "MLR-CALIB-SLOPE"]
        assert item and "0.5" in item[0]["basis"]

    def test_regression_skips_calibration(self) -> None:
        result = review_ml(
            _payload(
                run={
                    "task_type": "regression",
                    "selected_models": ["ridge", "lasso"],
                    "exploratory_mode": False,
                },
                calibration=None,
                comparison={
                    "ranking": ["ridge"],
                    "recommendation": {"primary_metric": "rmse"},
                    "charts": [],
                },
                table=[{"model_key": "ridge", "metrics": {"rmse": {"mean": 3.0, "std": 0.1}}}],
            )
        )
        assert "MLR-HL" not in _ids(result["minor_concerns"])
        assert "MLR-CALIB-SLOPE" not in _ids(result["minor_concerns"])


class TestClassImbalance:
    def test_imbalance_minor(self) -> None:
        result = review_ml(
            _payload(
                target_summary={
                    "n_samples": 1000,
                    "n_features": 8,
                    "prevalence": 0.08,
                    "positives": 80,
                }
            )
        )
        item = [c for c in result["minor_concerns"] if c["id"] == "MLR-IMBALANCE"]
        assert item and item[0]["dimension"] == "class_imbalance" and "8.0%" in item[0]["basis"]

    def test_extreme_imbalance_major(self) -> None:
        result = review_ml(
            _payload(
                target_summary={
                    "n_samples": 10000,
                    "n_features": 5,
                    "prevalence": 0.02,
                    "positives": 200,
                }
            )
        )
        assert "MLR-IMBALANCE-EXTREME" in _ids(result["major_concerns"])

    def test_balanced_no_concern(self) -> None:
        result = review_ml(_payload())
        assert "MLR-IMBALANCE" not in _ids(result["minor_concerns"])
        assert "MLR-IMBALANCE-EXTREME" not in _ids(result["major_concerns"])


class TestFeatureImportance:
    def test_no_explainability_minor(self) -> None:
        result = review_ml(
            _payload(
                comparison={
                    "ranking": ["xgboost"],
                    "recommendation": {"primary_metric": "auc"},
                    "charts": [],
                }
            )
        )
        assert "MLR-NO-EXPLAIN" in _ids(result["minor_concerns"])

    def test_dominant_feature_minor_and_question(self) -> None:
        """所有模型第二特征归一化重要性 <0.3 → 单特征主导，疑似结局代理。"""
        charts = [
            {
                "kind": "feature_importance",
                "data": {
                    "features": ["discharge_note", "age"],
                    "series": [
                        {"model_key": "xgboost", "values": [1.0, 0.2]},
                        {"model_key": "logistic", "values": [1.0, 0.1]},
                    ],
                },
            }
        ]
        result = review_ml(
            _payload(
                comparison={
                    "ranking": ["xgboost"],
                    "recommendation": {"primary_metric": "auc"},
                    "charts": charts,
                }
            )
        )
        item = [c for c in result["minor_concerns"] if c["id"] == "MLR-DOMINANT-FEATURE"]
        assert item and "discharge_note" in item[0]["basis"]
        assert "MLQ-PROXY" in _ids(result["questions"])

    def test_empty_payload_no_crash(self) -> None:
        result = review_ml({})
        assert isinstance(result["major_concerns"], list)
        # 验证配置缺失是 Major
        assert "MLR-NO-VALIDATION" in _ids(result["major_concerns"])
