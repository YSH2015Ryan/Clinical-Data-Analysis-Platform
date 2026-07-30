"""T3.1 预处理 DSL schema 单测（docs/06 §2、docs/14 PreprocessConfig；DoD：非法 DSL 400）。"""

import pytest
from app.engines.preprocessing import validate_dsl
from pydantic import ValidationError

VALID_DSL = {
    "target": {"time_col": "os_months", "event_col": "death"},
    "steps": [
        {
            "type": "reshape",
            "params": {
                "mode": "long_to_wide",
                "index": "患者ID",
                "columns": "检验名称",
                "values": "归一化值",
                "agg": "first",
            },
        },
        {"type": "drop_columns", "params": {"columns": ["patient_id"]}},
        {
            "type": "missing",
            "params": {"default": "median", "per_column": {"stage": "mode"}, "drop_threshold": 0.5},
        },
        {"type": "outlier", "params": {"method": "iqr", "action": "clip", "columns": "continuous"}},
        {
            "type": "encode",
            "params": {
                "method": "auto",
                "onehot_max_cardinality": 10,
                "ordinal_columns": {"stage": ["I", "II", "III", "IV"]},
            },
        },
        {"type": "scale", "params": {"method": "standard", "columns": "continuous"}},
        {"type": "feature_select", "params": {"method": "variance_threshold", "threshold": 0.0}},
        {
            "type": "derive",
            "params": {"expressions": [{"name": "followup_years", "expr": "os_months / 12"}]},
        },
    ],
    "validation": {"strategy": "stratified_kfold", "n_splits": 5, "test_size": 0.2, "seed": 42},
}


class TestValidDsl:
    def test_docs_example_roundtrip(self) -> None:
        cfg = validate_dsl(VALID_DSL)
        assert cfg.target.time_col == "os_months"
        assert len(cfg.steps) == 8
        assert cfg.validation.seed == 42
        # 序列化回字典可再次校验（幂等）
        validate_dsl(cfg.model_dump(mode="json"))

    def test_minimal_valid(self) -> None:
        cfg = validate_dsl(
            {
                "target": {"label_col": "death"},
                "steps": [{"type": "scale", "params": {}}],
                "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
            }
        )
        assert cfg.steps[0].params.method == "standard"  # 默认填充


class TestInvalidDsl:
    def test_unknown_step_type(self) -> None:
        bad = {**VALID_DSL, "steps": [{"type": "explode", "params": {}}]}
        with pytest.raises(ValidationError):
            validate_dsl(bad)

    def test_empty_steps(self) -> None:
        with pytest.raises(ValidationError):
            validate_dsl({**VALID_DSL, "steps": []})

    def test_missing_required_sections(self) -> None:
        with pytest.raises(ValidationError):
            validate_dsl({"steps": VALID_DSL["steps"]})

    def test_bad_missing_strategy(self) -> None:
        bad = {
            **VALID_DSL,
            "steps": [{"type": "missing", "params": {"default": "magic"}}],
        }
        with pytest.raises(ValidationError):
            validate_dsl(bad)

    def test_bad_per_column_strategy(self) -> None:
        bad = {
            **VALID_DSL,
            "steps": [{"type": "missing", "params": {"per_column": {"stage": "magic"}}}],
        }
        with pytest.raises(ValidationError, match="非法策略"):
            validate_dsl(bad)

    def test_threshold_out_of_range(self) -> None:
        bad = {
            **VALID_DSL,
            "steps": [{"type": "missing", "params": {"drop_threshold": 1.5}}],
        }
        with pytest.raises(ValidationError):
            validate_dsl(bad)

    def test_extra_param_rejected(self) -> None:
        bad = {
            **VALID_DSL,
            "steps": [{"type": "scale", "params": {"method": "standard", "hack": True}}],
        }
        with pytest.raises(ValidationError):
            validate_dsl(bad)

    def test_bad_derive_name(self) -> None:
        bad = {
            **VALID_DSL,
            "steps": [
                {"type": "derive", "params": {"expressions": [{"name": "1bad", "expr": "a + 1"}]}}
            ],
        }
        with pytest.raises(ValidationError, match="非法"):
            validate_dsl(bad)

    def test_bad_validation_strategy(self) -> None:
        bad = {**VALID_DSL, "validation": {"strategy": "holdout", "n_splits": 5, "seed": 42}}
        with pytest.raises(ValidationError):
            validate_dsl(bad)

    def test_n_splits_out_of_range(self) -> None:
        bad = {
            **VALID_DSL,
            "validation": {"strategy": "kfold", "n_splits": 99, "seed": 42},
        }
        with pytest.raises(ValidationError):
            validate_dsl(bad)
