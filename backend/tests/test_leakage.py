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


def test_name_similarity_flags_semantic_leakage() -> None:
    """updateplan §21：特征名包含目标名（或反之）→ 疑似语义泄漏 warning。"""
    df = pd.DataFrame(
        {
            "diabetes_status": [0, 1, 0, 1],
            # 与目标不相同也不近完全相关（避免先被 TARGET_PROXY 拦截），仅名相似
            "diabetes": [0, 1, 1, 0],
            "diabetes_result": [0, 1, 1, 0],
            "age": [50, 60, 55, 65],
        }
    )
    result = inspect_leakage(df, target_col="diabetes_status")
    finding = next(f for f in result.findings if f.code == "NAME_SIMILARITY")
    assert finding.severity == "warning"
    assert set(finding.columns) == {"diabetes", "diabetes_result"}
    assert "age" not in finding.columns


def test_name_similarity_ignores_short_names() -> None:
    """短列名（<3 字符归一化后）不做子串匹配，避免 x/y 类误报。"""
    df = pd.DataFrame({"y": [0, 1, 0, 1], "xy": [1, 2, 3, 4]})
    result = inspect_leakage(df, target_col="y")
    assert not any(f.code == "NAME_SIMILARITY" for f in result.findings)


def test_date_derived_target_flags_critical() -> None:
    """updateplan §24：month_group 类目标 + 日期族特征 → CRITICAL 提示。

    severity 为 critical（醒目复核）而非 blocker（不硬阻断，§72 Gate 前）。"""
    df = pd.DataFrame(
        {
            "month_group": [0, 1, 0, 1],
            "month": [1, 2, 3, 4],
            "Year": [2023, 2023, 2024, 2024],
            "seasons": ["春", "夏", "秋", "冬"],
            "Jieqi": ["立春", "立夏", "立秋", "立冬"],
            "age": [50, 60, 55, 65],
        }
    )
    result = inspect_leakage(df, target_col="month_group")
    finding = next(f for f in result.findings if f.code == "DATE_DERIVED_TARGET")
    assert finding.severity == "critical"
    assert set(finding.columns) >= {"month", "Year", "seasons", "Jieqi"}
    assert "age" not in finding.columns
    assert not result.has_blocking_issue  # critical 不硬阻断


def test_date_derived_target_requires_date_features() -> None:
    """目标名像日期派生但无日期族特征 → 不报（避免误伤）。"""
    df = pd.DataFrame({"month_group": [0, 1, 0, 1], "age": [50, 60, 55, 65]})
    result = inspect_leakage(df, target_col="month_group")
    assert not any(f.code == "DATE_DERIVED_TARGET" for f in result.findings)


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
