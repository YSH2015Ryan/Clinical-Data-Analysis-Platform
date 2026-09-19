"""§78 Analysis Manifest（P3-05）引擎契约测试。

manifest 全部字段来自真实记录（DB/存储）；excluded_variables 为
预处理 drop_columns 与 quickfix drop_column 的并集（排序去重）；
未显式传参的模型 parameters 为空 dict（库默认值，不编造）。
"""

from typing import Any

from app.engines.manifest import MANIFEST_SCHEMA_VERSION, build_manifest


def _kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run": {
            "id": "run-1",
            "task_type": "classification",
            "status": "COMPLETED",
            "exploratory_mode": False,
            "created_at": "2026-09-18T10:00:00",
            "finished_at": "2026-09-18T10:05:00",
            "preprocess_config": {
                "validation": {"strategy": "stratified_kfold", "n_splits": 5, "seed": 42},
                "target": {"label_col": "outcome"},
            },
            "model_params": {"xgboost": {"max_depth": 4}},
        },
        "dataset": {"name": "demo", "id": "ds-1", "version_no": 2},
        "input_hash": "abc123",
        "preprocess_steps": [
            {"type": "drop_columns", "params": {"columns": ["patient_id", "name"]}},
            {"type": "missing", "params": {"default": "median"}},
        ],
        "transform_log": [{"actions": [{"type": "drop_column", "column": "mrn"}]}],
        "results": [
            {"model_key": "xgboost", "status": "SUCCESS", "duration_ms": 1200},
            {"model_key": "logistic", "status": "FAILED", "duration_ms": None},
        ],
        "comparison": {
            "ranking": ["xgboost"],
            "recommendation": {
                "primary_metric": "auc",
                "top": [{"model_key": "xgboost", "reason": "AUC 最高"}],
            },
        },
        "software": {"app": "2.0.0", "python": "3.11"},
    }
    base.update(over)
    return base


class TestContract:
    def test_section78_fields(self) -> None:
        m = build_manifest(**_kwargs())
        assert m["schema_version"] == MANIFEST_SCHEMA_VERSION
        assert m["dataset"]["dataset_hash"] == "abc123"
        assert m["analysis_version"] == "2.0.0"
        assert m["random_seed"] == 42
        assert m["validation"] == {"strategy": "stratified_kfold", "folds": 5, "seed": 42}
        assert m["target"] == {"label_col": "outcome"}
        assert m["excluded_variables"] == ["mrn", "name", "patient_id"]
        params = {x["model_key"]: x["parameters"] for x in m["models"]}
        assert params["xgboost"] == {"max_depth": 4}
        assert params["logistic"] == {}  # 未传参 → 空 dict，不编造默认值

    def test_section77_reproducibility_fields(self) -> None:
        m = build_manifest(**_kwargs())
        assert m["analysis_id"] == "run-1"
        assert m["created_at"] and m["finished_at"]
        assert m["software"]["python"] == "3.11"
        assert m["result_summary"]["top_model"] == "xgboost"

    def test_deterministic(self) -> None:
        assert build_manifest(**_kwargs()) == build_manifest(**_kwargs())


class TestMissingData:
    def test_no_comparison(self) -> None:
        m = build_manifest(**_kwargs(comparison=None))
        assert m["result_summary"] is None

    def test_no_validation_config(self) -> None:
        run = dict(_kwargs()["run"])
        run["preprocess_config"] = {}
        m = build_manifest(**_kwargs(run=run))
        assert m["random_seed"] is None
        assert m["validation"] == {"strategy": None, "folds": None, "seed": None}

    def test_no_exclusions(self) -> None:
        m = build_manifest(**_kwargs(preprocess_steps=None, transform_log=None))
        assert m["excluded_variables"] == []

    def test_duplicate_exclusions_deduped(self) -> None:
        steps = [
            {"type": "drop_columns", "params": {"columns": ["a", "b"]}},
            {"type": "drop_columns", "params": {"columns": ["a"]}},
        ]
        m = build_manifest(**_kwargs(preprocess_steps=steps, transform_log=None))
        assert m["excluded_variables"] == ["a", "b"]
