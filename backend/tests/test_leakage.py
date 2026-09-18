"""P0 leakage engine regression tests."""

import pandas as pd

from app.engines.leakage import inspect_leakage


def test_detects_target_proxy_duplicate_and_future_columns() -> None:
    df = pd.DataFrame(
        {
            "patient_id": [1, 1, 2, 3],
            "label": [0, 1, 0, 1],
            "label_copy": [0, 1, 0, 1],
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "post_outcome": [0, 1, 0, 1],
        }
    )
    result = inspect_leakage(
        df,
        target_col="label",
        group_col="patient_id",
        prediction_time_col="date",
        feature_time_columns={"post_outcome": "2024-01-05"},
    )
    codes = {finding.code for finding in result.findings}
    assert "TARGET_PROXY" in codes
    assert "DUPLICATE_PATIENT" in codes
    assert "PREDICTION_TIME_UNDEFINED" not in codes
    assert "FUTURE_FEATURE" in codes


def test_prediction_time_is_required_when_temporal_data_is_declared() -> None:
    df = pd.DataFrame({"label": [0, 1], "value": [1.0, 2.0]})
    result = inspect_leakage(df, target_col="label", temporal=True)
    assert any(f.code == "PREDICTION_TIME_UNDEFINED" for f in result.findings)
    assert result.has_blocking_issue
