"""Tests for the rule-based research direction profiler."""

import pandas as pd
from app.engines.research_profiler import detect_research_direction


def test_detect_cross_sectional() -> None:
    result = detect_research_direction(pd.DataFrame({"age": [30, 40], "outcome": [0, 1]}))
    assert result["research_type"] == "cross_sectional"


def test_detect_cohort_study() -> None:
    result = detect_research_direction(
        pd.DataFrame({"os_months": [1, 2, 3], "death": [0, 1, 0], "age": [40, 50, 60]})
    )
    assert result["research_type"] == "cohort"


def test_detect_time_series() -> None:
    result = detect_research_direction(
        pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "cases": [1, 2, 3]})
    )
    assert result["research_type"] == "time_series"


def test_recommend_models_regression() -> None:
    result = detect_research_direction(
        pd.DataFrame({"age": [30, 40, 50], "outcome": [1.2, 2.5, 4.0]}),
        {"outcome": "outcome"},
    )
    assert result["recommended_models"] == ["lasso", "rf_reg", "xgboost_reg"]


def test_recommend_models_survival() -> None:
    result = detect_research_direction(pd.DataFrame({"follow_up": [1, 2, 3], "event": [0, 1, 0]}))
    assert "coxph" in result["recommended_models"]
    assert "rsf" in result["recommended_models"]


def test_recommend_journals() -> None:
    result = detect_research_direction(
        pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "cases": [1, 2, 3]})
    )
    assert "Environmental Health Perspectives" in result["recommended_journals"]
    assert result["confidence"] <= 1.0
