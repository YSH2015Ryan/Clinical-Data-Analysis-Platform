"""T6.2 对比图表装配单测（docs/09 §3、§6；docs/19）。

- 三类任务图表清单齐备；DCA 净获益公式；特征重要性归一化 Top-N；
- 数据只来自真实计算产物（合成 rows 模拟 ModelResult 产物）。
"""

import math

from app.engines.comparison.charts import build_comparison_charts

PREVALENCE = 0.5


def _clf_rows() -> list[dict]:
    return [
        {
            "model_key": "logreg",
            "metrics": {
                "auc": {"mean": 0.8, "std": 0.02, "folds": [0.8, 0.8, 0.8]},
                "brier": {"mean": 0.15, "std": 0.01, "folds": [0.15, 0.15, 0.15]},
            },
            "artifacts": {
                "roc_curve": {
                    "fpr": [0.0, 0.1, 1.0],
                    "tpr": [0.0, 0.9, 1.0],
                    "thresholds": [None, 0.7, 0.2],
                },
                "calibration_curve": {"prob_true": [0.1, 0.9], "prob_pred": [0.2, 0.8]},
                "confusion_matrix": {"labels": [0, 1], "matrix": [[40, 10], [5, 45]]},
            },
            "explainability": {
                "type": "feature_importance",
                "importances": {"age": 0.5, "bmi": 0.2},
            },
        },
        {
            "model_key": "rf",
            "metrics": {"auc": {"mean": 0.9, "std": 0.01, "folds": [0.9, 0.9, 0.9]}},
            "artifacts": {
                "roc_curve": {
                    "fpr": [0.0, 0.05, 1.0],
                    "tpr": [0.0, 0.95, 1.0],
                    "thresholds": [None, 0.8, 0.1],
                },
                "calibration_curve": {"prob_true": [0.1, 0.9], "prob_pred": [0.1, 0.9]},
                "confusion_matrix": {"labels": [0, 1], "matrix": [[45, 5], [3, 47]]},
            },
            "explainability": {
                "type": "shap_summary",
                "importances": {"age": 0.9, "glucose": 0.7},
            },
        },
    ]


class TestClassificationCharts:
    def test_kinds_complete(self) -> None:
        charts = build_comparison_charts("classification", _clf_rows(), prevalence=PREVALENCE)
        assert {c["kind"] for c in charts} == {
            "roc",
            "pr_curve",
            "calibration",
            "dca",
            "confusion_matrix",
            "feature_importance",
        }
        for c in charts:  # ChartAsset 契约字段（docs/14）
            assert c["title"]
            assert c["image_uri"] is None

    def test_pr_curve_precision_formula(self) -> None:
        """precision = tpr·π / (tpr·π + fpr·(1−π))（P3，PR 曲线由 ROC 产物精确推导）。"""
        charts = build_comparison_charts("classification", _clf_rows(), prevalence=PREVALENCE)
        pr = next(c for c in charts if c["kind"] == "pr_curve")
        series = next(s for s in pr["data"]["series"] if s["model_key"] == "logreg")
        # logreg: fpr=[0, 0.1, 1], tpr=[0, 0.9, 1], π=0.5
        # tpr=0.9, fpr=0.1 → 0.45 / 0.5 = 0.9
        idx = series["recall"].index(0.9)
        assert math.isclose(series["precision"][idx], 0.9, rel_tol=1e-9)
        # tpr=1.0, fpr=1.0 → precision = π = 0.5
        idx = series["recall"].index(1.0)
        assert math.isclose(series["precision"][idx], PREVALENCE, rel_tol=1e-9)
        # AUPRC 在 [π, 1] 之间（优于随机的模型）
        assert PREVALENCE <= series["auprc"] <= 1.0
        assert pr["data"]["prevalence"] == PREVALENCE

    def test_pr_curve_skipped_without_prevalence(self) -> None:
        charts = build_comparison_charts("classification", _clf_rows())
        assert "pr_curve" not in {c["kind"] for c in charts}

    def test_roc_overlay_auc_from_metrics(self) -> None:
        charts = build_comparison_charts("classification", _clf_rows(), prevalence=PREVALENCE)
        roc = next(c for c in charts if c["kind"] == "roc")
        assert len(roc["data"]["series"]) == 2
        first = roc["data"]["series"][0]
        assert first["model_key"] == "logreg"
        assert first["auc"] == 0.8
        assert len(first["fpr"]) == len(first["tpr"])

    def test_dca_net_benefit_formula(self) -> None:
        """NB(t) = tpr·π − fpr·(1−π)·t/(1−t)（docs/09 §3 净获益公式）。"""
        charts = build_comparison_charts("classification", _clf_rows(), prevalence=PREVALENCE)
        dca = next(c for c in charts if c["kind"] == "dca")
        series = next(s for s in dca["data"]["series"] if s["model_key"] == "logreg")
        # t=0.7, tpr=0.9, fpr=0.1 → 0.9*0.5 − 0.1*0.5*0.7/0.3
        idx = series["thresholds"].index(0.7)
        expected = 0.9 * 0.5 - 0.1 * 0.5 * 0.7 / 0.3
        assert math.isclose(series["net_benefit"][idx], expected, rel_tol=1e-9)
        # treat-all：t→0 时趋近患病率
        treat_all = dca["data"]["treat_all"]
        assert math.isclose(treat_all["net_benefit"][0], PREVALENCE, abs_tol=0.01)

    def test_confusion_passthrough(self) -> None:
        charts = build_comparison_charts("classification", _clf_rows(), prevalence=PREVALENCE)
        cm = next(c for c in charts if c["kind"] == "confusion_matrix")
        logreg = next(m for m in cm["data"]["models"] if m["model_key"] == "logreg")
        assert logreg["matrix"] == [[40, 10], [5, 45]]
        assert sum(sum(r) for r in logreg["matrix"]) == 100

    def test_feature_importance_top_n_normalized(self) -> None:
        charts = build_comparison_charts("classification", _clf_rows(), prevalence=PREVALENCE)
        fi = next(c for c in charts if c["kind"] == "feature_importance")
        # 并集按跨模型最大重要性排序：age(0.9) > glucose(0.7) > bmi(0.2)
        assert fi["data"]["features"] == ["age", "glucose", "bmi"]
        for series in fi["data"]["series"]:
            assert max(series["values"]) == 1.0  # 各模型自身归一
        logreg = next(s for s in fi["data"]["series"] if s["model_key"] == "logreg")
        assert logreg["values"][1] == 0.0  # glucose 未出现 → 0

    def test_coefficients_as_importance(self) -> None:
        rows = [
            {
                "model_key": "logreg",
                "metrics": {},
                "artifacts": {},
                "explainability": {
                    "type": "coefficients",
                    "table": [
                        {"feature": "age", "coef": 0.5},
                        {"feature": "bmi", "coef": -0.3},
                    ],
                },
            }
        ]
        charts = build_comparison_charts("classification", rows, prevalence=PREVALENCE)
        fi = next(c for c in charts if c["kind"] == "feature_importance")
        assert fi["data"]["features"] == ["age", "bmi"]  # |coef| 排序

    def test_dca_skipped_without_prevalence(self) -> None:
        charts = build_comparison_charts("classification", _clf_rows())
        assert "dca" not in {c["kind"] for c in charts}


def _surv_rows() -> list[dict]:
    return [
        {
            "model_key": "km",
            "metrics": {"c_index": {"mean": 0.5, "std": 0.0, "folds": [0.5, 0.5, 0.5]}},
            "artifacts": {
                "km_curve": {
                    "times": [1.0, 2.0, 3.0],
                    "survival": [0.9, 0.8, 0.7],
                    "ci_lower": [0.8, 0.7, 0.6],
                    "ci_upper": [1.0, 0.9, 0.8],
                }
            },
            "explainability": None,
        },
        {
            "model_key": "coxph",
            "metrics": {"c_index": {"mean": 0.7, "std": 0.1, "folds": [0.7, 0.7, 0.7]}},
            "artifacts": {
                "hr_forest": [
                    {"feature": "age", "hr": 1.5, "ci_lower": 1.1, "ci_upper": 2.0, "p_value": 0.01}
                ],
                "km_by_risk": {
                    "groups": [
                        {"name": "低风险", "times": [1.0, 2.0], "survival": [0.95, 0.9]},
                        {"name": "高风险", "times": [1.0, 2.0], "survival": [0.8, 0.6]},
                    ]
                },
            },
            "explainability": {
                "type": "coefficients",
                "table": [{"feature": "age", "coef": 0.4}],
            },
        },
    ]


class TestSurvivalCharts:
    def test_kinds_complete(self) -> None:
        charts = build_comparison_charts("survival", _surv_rows())
        assert {c["kind"] for c in charts} == {
            "km",
            "cindex_forest",
            "hr_forest",
            "feature_importance",
        }

    def test_km_series_groups(self) -> None:
        charts = build_comparison_charts("survival", _surv_rows())
        km = next(c for c in charts if c["kind"] == "km")
        groups = {(s["model_key"], s["group"]) for s in km["data"]["series"]}
        assert ("km", "总体") in groups
        assert ("coxph", "低风险") in groups
        assert ("coxph", "高风险") in groups

    def test_cindex_forest_ci(self) -> None:
        charts = build_comparison_charts("survival", _surv_rows())
        forest = next(c for c in charts if c["kind"] == "cindex_forest")
        rows = forest["data"]["rows"]
        assert rows[0]["model_key"] == "coxph"  # 按 c_index 降序
        assert math.isclose(rows[0]["ci_lower"], 0.7 - 1.96 * 0.1, rel_tol=1e-9)
        assert math.isclose(rows[0]["ci_upper"], 0.7 + 1.96 * 0.1, rel_tol=1e-9)

    def test_hr_forest_passthrough(self) -> None:
        charts = build_comparison_charts("survival", _surv_rows())
        hr = next(c for c in charts if c["kind"] == "hr_forest")
        assert hr["data"]["models"][0]["rows"][0]["hr"] == 1.5


class TestRegressionCharts:
    def test_scatter_and_importance(self) -> None:
        rows = [
            {
                "model_key": "lasso",
                "metrics": {"rmse": {"mean": 2.5, "std": 0.3, "folds": [2.5, 2.5, 2.5]}},
                "artifacts": {"prediction_scatter": {"y_true": [1.0, 2.0], "y_pred": [1.1, 1.9]}},
                "explainability": {
                    "type": "feature_importance",
                    "importances": {"age": 0.8},
                },
            }
        ]
        charts = build_comparison_charts("regression", rows)
        # P1-14（§44）：回归图表 = 散点 + 残差图 + 特征重要性
        assert {c["kind"] for c in charts} == {
            "prediction_scatter",
            "residual_plot",
            "feature_importance",
        }
        scatter = next(c for c in charts if c["kind"] == "prediction_scatter")
        assert scatter["data"]["series"][0]["rmse"] == 2.5


class TestEdgeCases:
    def test_empty_rows(self) -> None:
        assert build_comparison_charts("classification", [], prevalence=0.5) == []
        assert build_comparison_charts("survival", []) == []
        assert build_comparison_charts("regression", []) == []

    def test_missing_artifacts_skipped(self) -> None:
        rows = [
            {
                "model_key": "dummy",
                "metrics": {"auc": {"mean": 0.5, "std": 0.0, "folds": [0.5]}},
                "artifacts": {},
                "explainability": None,
            }
        ]
        assert build_comparison_charts("classification", rows, prevalence=0.5) == []
