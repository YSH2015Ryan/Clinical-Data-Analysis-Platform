"""T6.9 科研流程模板库引擎测试（先行，对应 docs/19）。

模板输出只引用 df 真实统计（行数/事件数/特征数），不虚构数值（红线8）。
"""

import pandas as pd
import pytest
from app.engines.research_templates import (
    KNOWN_CHART_KINDS,
    KNOWN_MODEL_KEYS,
    evaluate_templates,
    list_templates,
)


def _cohort_df(n: int = 200, events: int = 60) -> pd.DataFrame:
    """队列/生存数据：随访时间 + 0/1 事件 + 若干特征。"""
    rows = {
        "follow_up_days": [30 + i % 400 for i in range(n)],
        "death_event": [1] * events + [0] * (n - events),
        "age": [40 + i % 30 for i in range(n)],
        "bmi": [20.0 + (i % 10) for i in range(n)],
        "smoking": [i % 2 for i in range(n)],
    }
    return pd.DataFrame(rows)


def _binary_df(n: int = 120, positives: int = 40) -> pd.DataFrame:
    """二分类结局（无随访列）。"""
    return pd.DataFrame(
        {
            "outcome": [1] * positives + [0] * (n - positives),
            "age": [50 + i % 20 for i in range(n)],
            "sex": [i % 2 for i in range(n)],
        }
    )


def _continuous_df(n: int = 150) -> pd.DataFrame:
    """连续结局（无随访列）。"""
    return pd.DataFrame(
        {
            "outcome_score": [float(i % 50) for i in range(n)],
            "dose_mg": [10.0 + i % 40 for i in range(n)],
            "age": [30 + i % 25 for i in range(n)],
        }
    )


def _longitudinal_df(n: int = 300) -> pd.DataFrame:
    """纵向数据：时间索引 + 连续结局。"""
    return pd.DataFrame(
        {
            "visit_date": pd.date_range("2024-01-01", periods=n, freq="D").astype(str),
            "outcome_score": [float(i % 40) for i in range(n)],
            "dose_mg": [5.0 + i % 30 for i in range(n)],
        }
    )


def _by_key(templates: list[dict], key: str) -> dict:
    match = [t for t in templates if t["key"] == key]
    assert match, f"模板 {key} 缺失"
    return match[0]


class TestListTemplates:
    def test_four_templates(self) -> None:
        templates = list_templates()
        assert len(templates) == 4
        assert {t["key"] for t in templates} == {
            "prognostic_model",
            "risk_factor",
            "dose_response",
            "longitudinal",
        }

    def test_models_and_charts_whitelisted(self) -> None:
        for t in list_templates():
            assert set(t["models"]) <= KNOWN_MODEL_KEYS
            assert set(t["charts"]) <= KNOWN_CHART_KINDS
            assert t["name"] and t["description"]


class TestPrognosticModel:
    def test_cohort_applicable_survival(self) -> None:
        result = evaluate_templates(_cohort_df())
        t = _by_key(result, "prognostic_model")
        assert t["applicable"] is True
        assert t["task_type"] == "survival"
        assert set(t["models"]) == {"coxph", "rsf", "gbs"}
        assert "km" in t["charts"]

    def test_epv_real_numbers(self) -> None:
        df = _cohort_df(n=200, events=60)
        t = _by_key(evaluate_templates(df), "prognostic_model")
        epv = next(a for a in t["sample_size"] if "EPV" in a["rule"])
        # 特征数 = 总列数 - time/event 列 = 5 - 2 = 3
        assert epv["value"] == pytest.approx(60 / 3)
        assert epv["threshold"] == 10
        assert epv["meets"] is True
        assert "60" in epv["text"]  # 文本含真实事件数

    def test_epv_below_threshold(self) -> None:
        df = _cohort_df(n=60, events=15)
        t = _by_key(evaluate_templates(df), "prognostic_model")
        epv = next(a for a in t["sample_size"] if "EPV" in a["rule"])
        assert epv["value"] == pytest.approx(15 / 3)
        assert epv["meets"] is False

    def test_binary_outcome_fallback_classification(self) -> None:
        t = _by_key(evaluate_templates(_binary_df()), "prognostic_model")
        assert t["applicable"] is True
        assert t["task_type"] == "classification"
        assert "logreg" in t["models"]

    def test_not_applicable_without_outcome(self) -> None:
        df = pd.DataFrame({"a": range(50), "b": range(50)})
        t = _by_key(evaluate_templates(df), "prognostic_model")
        assert t["applicable"] is False
        assert t["reasons"]


class TestRiskFactor:
    def test_binary_outcome_applicable(self) -> None:
        t = _by_key(evaluate_templates(_binary_df()), "risk_factor")
        assert t["applicable"] is True
        assert t["task_type"] == "classification"
        assert set(t["models"]) == {"logreg", "rf", "xgboost"}

    def test_epv_uses_positives(self) -> None:
        df = _binary_df(n=120, positives=40)
        t = _by_key(evaluate_templates(df), "risk_factor")
        epv = next(a for a in t["sample_size"] if "EPV" in a["rule"])
        # 少数类 = 40；特征 = 3 - 1 = 2
        assert epv["value"] == pytest.approx(40 / 2)

    def test_not_applicable_without_binary_outcome(self) -> None:
        t = _by_key(evaluate_templates(_continuous_df()), "risk_factor")
        assert t["applicable"] is False


class TestDoseResponse:
    def test_continuous_outcome_applicable(self) -> None:
        t = _by_key(evaluate_templates(_continuous_df()), "dose_response")
        assert t["applicable"] is True
        assert t["task_type"] == "regression"
        assert set(t["models"]) == {"gam", "lasso", "rf_reg"}

    def test_n_per_predictor_rule(self) -> None:
        df = _continuous_df(n=150)
        t = _by_key(evaluate_templates(df), "dose_response")
        advice = next(a for a in t["sample_size"] if "n/p" in a["rule"].lower())
        # n=150, 特征 = 3 - 1 = 2 → 75
        assert advice["value"] == pytest.approx(75.0)
        assert advice["threshold"] == 20
        assert advice["meets"] is True

    def test_small_sample_fails(self) -> None:
        df = _continuous_df(n=30)
        t = _by_key(evaluate_templates(df), "dose_response")
        advice = t["sample_size"][0]
        assert advice["value"] == pytest.approx(15.0)
        assert advice["meets"] is False
        assert "30" in advice["text"]


class TestLongitudinal:
    def test_time_plus_continuous_applicable(self) -> None:
        t = _by_key(evaluate_templates(_longitudinal_df()), "longitudinal")
        assert t["applicable"] is True
        assert t["task_type"] == "regression"
        assert "gee" in t["models"]

    def test_not_applicable_without_time(self) -> None:
        t = _by_key(evaluate_templates(_continuous_df()), "longitudinal")
        assert t["applicable"] is False

    def test_min_sample_rule(self) -> None:
        df = _longitudinal_df(n=40)
        t = _by_key(evaluate_templates(df), "longitudinal")
        advice = t["sample_size"][0]
        assert advice["value"] == 40
        assert advice["meets"] is False


class TestCommonContract:
    def test_result_shape(self) -> None:
        for t in evaluate_templates(_cohort_df()):
            for field in (
                "key",
                "name",
                "description",
                "applicable",
                "reasons",
                "task_type",
                "models",
                "charts",
                "sample_size",
            ):
                assert field in t, f"缺少字段 {field}"
            assert t["task_type"] in {"survival", "classification", "regression"}
            for advice in t["sample_size"]:
                for field in ("rule", "value", "threshold", "meets", "text"):
                    assert field in advice

    def test_empty_df_no_crash(self) -> None:
        result = evaluate_templates(pd.DataFrame({"a": []}))
        assert len(result) == 4
        assert all(t["applicable"] is False for t in result)

    def test_hints_respected(self) -> None:
        df = _binary_df().rename(columns={"outcome": "label_x"})
        result = evaluate_templates(df, {"outcome": "label_x"})
        t = _by_key(result, "risk_factor")
        assert t["applicable"] is True
