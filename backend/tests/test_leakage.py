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


def test_dsl_feature_time_columns_reach_engine() -> None:
    """P0-03 接通回归：DSL validation.feature_time_columns 经 worker 调用形参
    传入引擎后必须触发 FUTURE_FEATURE（此前 worker 未传该参数，规则空转）。"""
    from app.engines.preprocessing import validate_dsl

    cfg = validate_dsl(
        {
            "target": {"label_col": "label"},
            "steps": [{"type": "scale", "params": {}}],
            "validation": {
                "strategy": "time_series_split",
                "n_splits": 3,
                "seed": 42,
                "time_col": "date",
                "prediction_time_col": "date",
                "feature_time_columns": {"post_outcome": "2024-01-05"},
            },
        }
    )
    df = pd.DataFrame(
        {
            "label": [0, 1, 0, 1],
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "post_outcome": [0, 1, 0, 1],
        }
    )
    # 与 worker（analysis_tasks.preprocess_run）调用形参保持一致
    result = inspect_leakage(
        df,
        target_col=cfg.target.label_col or "",
        group_col=cfg.validation.group_col,
        prediction_time_col=cfg.validation.prediction_time_col,
        feature_time_columns=cfg.validation.feature_time_columns,
        temporal=cfg.validation.strategy == "time_series_split",
    )
    assert any(f.code == "FUTURE_FEATURE" for f in result.findings)
