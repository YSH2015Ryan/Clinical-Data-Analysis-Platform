"""T3.4 防泄漏 + Snapshot + 可重放（docs/06 §4；docs/18 T3.4 DoD）。

DoD：
- 泄漏断言：每折 CV 内 fit 仅用训练折，统计量与训练折一致而非全量；
- 可重放：同一输入两次运行，特征矩阵逐位相等；
- Snapshot：步骤顺序/参数/拟合统计量/输入 hash/库版本，JSON 可序列化。
"""

import json

import numpy as np
import pandas as pd
import pytest
from app.engines.pipeline import (
    build_pipeline,
    iter_cv_splits,
    run_preprocess,
)
from app.engines.preprocessing import validate_dsl

DSL = {
    "target": {"label_col": "death"},
    "steps": [
        {"type": "missing", "params": {"default": "median"}},
        {"type": "outlier", "params": {"method": "iqr", "action": "clip"}},
        {"type": "encode", "params": {"method": "onehot"}},
        {"type": "scale", "params": {"method": "standard"}},
        {"type": "feature_select", "params": {"method": "variance_threshold", "threshold": 0.0}},
        {"type": "derive", "params": {"expressions": [{"name": "wbc_sq", "expr": "wbc * wbc"}]}},
    ],
    "validation": {"strategy": "kfold", "n_splits": 3, "seed": 42},
}


@pytest.fixture()
def df() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 60
    return pd.DataFrame(
        {
            "age": rng.uniform(20, 80, n).round(1),
            "wbc": rng.uniform(3, 15, n).round(2),
            "gender": rng.choice(["男", "女"], n),
        }
    )


class TestBuildPipeline:
    def test_all_step_types_mapped(self) -> None:
        cfg = validate_dsl(DSL)
        pipe = build_pipeline(cfg)
        assert len(pipe.steps) == 6
        assert [name.split("_", 1)[1] for name, _ in pipe.steps] == [
            "missing",
            "outlier",
            "encode",
            "scale",
            "feature_select",
            "derive",
        ]

    def test_reshape_and_drop_columns_mapped(self) -> None:
        cfg = validate_dsl(
            {
                "target": {"label_col": "death"},
                "steps": [
                    {
                        "type": "reshape",
                        "params": {
                            "mode": "long_to_wide",
                            "index": "pid",
                            "columns": "item",
                            "values": "val",
                            "agg": "first",
                        },
                    },
                    {"type": "drop_columns", "params": {"columns": ["junk"]}},
                ],
                "validation": {"strategy": "kfold", "n_splits": 2, "seed": 42},
            }
        )
        pipe = build_pipeline(cfg)
        assert len(pipe.steps) == 2


class TestLeakageGuard:
    def test_fit_statistics_from_train_fold_only(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(DSL)
        y = pd.Series([0, 1] * 30)
        for train_idx, val_idx in iter_cv_splits(df, cfg.validation, y):
            train, val = df.iloc[train_idx], df.iloc[val_idx]
            pipe = build_pipeline(cfg)
            pipe.fit(train, y.iloc[train_idx])
            # scale 统计量必须等于训练折统计量，而非全量
            center = pipe.named_steps["3_scale"].statistics_["params"]["age"]["center"]
            assert center == pytest.approx(train["age"].mean())
            assert center != pytest.approx(df["age"].mean())
            # 缺失插补值来自训练折中位数
            fill = pipe.named_steps["0_missing"].statistics_["fill_values"].get("age")
            assert fill is None or fill == pytest.approx(train["age"].median())
            out = pipe.transform(val)
            assert out.isna().sum().sum() == 0

    def test_folds_disjoint_and_cover_all(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(DSL)
        y = pd.Series([0, 1] * 30)
        seen: set[int] = set()
        for train_idx, val_idx in iter_cv_splits(df, cfg.validation, y):
            assert set(train_idx).isdisjoint(set(val_idx))
            seen |= set(val_idx)
        assert seen == set(range(len(df)))

    def test_stratified_requires_y(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(
            {**DSL, "validation": {"strategy": "stratified_kfold", "n_splits": 2, "seed": 42}}
        )
        with pytest.raises(ValueError, match="y"):
            list(iter_cv_splits(df, cfg.validation, None))

    def test_stratified_preserves_class_ratio(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(
            {**DSL, "validation": {"strategy": "stratified_kfold", "n_splits": 3, "seed": 42}}
        )
        y = pd.Series([0] * 40 + [1] * 20)  # 2:1 不平衡
        for _, val_idx in iter_cv_splits(df, cfg.validation, y):
            ratio = y.iloc[val_idx].mean()
            assert ratio == pytest.approx(1 / 3, abs=0.06)


class TestReplayDeterminism:
    def test_feature_matrix_bitwise_identical(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(DSL)
        y = pd.Series([0, 1] * 30)
        r1 = run_preprocess(df, cfg, y=y, input_hash="a" * 64)
        r2 = run_preprocess(df, cfg, y=y, input_hash="a" * 64)
        pd.testing.assert_frame_equal(r1.features, r2.features, check_exact=True)
        assert r1.snapshot == r2.snapshot
        assert r1.summary == r2.summary


class TestSnapshot:
    def test_snapshot_json_serializable_and_complete(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(DSL)
        y = pd.Series([0, 1] * 30)
        result = run_preprocess(df, cfg, y=y, input_hash="b" * 64)
        snap = result.snapshot
        json.dumps(snap)  # 必须可 JSON 序列化（写入 JSONB 前提）
        assert snap["input_hash"] == "b" * 64
        assert snap["seed"] == 42
        assert [s["type"] for s in snap["steps"]] == [
            "missing",
            "outlier",
            "encode",
            "scale",
            "feature_select",
            "derive",
        ]
        for i, s in enumerate(snap["steps"]):
            assert s["order"] == i
            assert "params" in s and "statistics" in s
        versions = snap["library_versions"]
        for lib in ("pandas", "numpy", "sklearn", "simpleeval"):
            assert lib in versions

    def test_summary_tracks_rows_cols(self, df: pd.DataFrame) -> None:
        cfg = validate_dsl(DSL)
        y = pd.Series([0, 1] * 30)
        result = run_preprocess(df, cfg, y=y, input_hash="c" * 64)
        assert len(result.summary) == 6
        first = result.summary[0]
        assert first["step"] == "missing"
        assert first["rows_in"] == 60 and first["rows_out"] == 60
        assert first["cols_in"] == 3


class TestReshapeStep:
    def test_long_to_wide_and_fold_consistency(self) -> None:
        long_df = pd.DataFrame(
            {
                "pid": [1, 1, 2, 2, 3],
                "item": ["wbc", "crp", "wbc", "crp", "wbc"],
                "val": [5.0, 10.0, 6.0, 12.0, 7.0],
            }
        )
        cfg = validate_dsl(
            {
                "target": {"label_col": "death"},
                "steps": [
                    {
                        "type": "reshape",
                        "params": {
                            "mode": "long_to_wide",
                            "index": "pid",
                            "columns": "item",
                            "values": "val",
                            "agg": "first",
                        },
                    }
                ],
                "validation": {"strategy": "kfold", "n_splits": 2, "seed": 42},
            }
        )
        pipe = build_pipeline(cfg)
        wide = pipe.fit_transform(long_df)
        assert set(wide.columns) == {"pid", "wbc", "crp"}
        assert wide.loc[wide["pid"] == 1, "wbc"].iloc[0] == 5.0
        # 验证折缺少某类别 → 仍输出训练折列（reindex 对齐，NaN 兜底）
        val = pd.DataFrame({"pid": [4, 4], "item": ["wbc", "wbc"], "val": [8.0, 9.0]})
        out = pipe.transform(val)
        assert set(out.columns) == {"pid", "wbc", "crp"}
        assert out["crp"].isna().all()
