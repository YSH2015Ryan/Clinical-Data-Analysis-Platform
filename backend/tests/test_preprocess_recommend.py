"""T3.5 推荐默认配置生成器（docs/06 §2「推荐默认配置」按钮、§3.1 长表适配）。

DoD（docs/18 T3.5）：对测试数据生成的 DSL 可直接运行成功。
依赖：T2.3 列类型/语义识别、T3.2~T3.4 步骤与编排。
"""

import numpy as np
import pandas as pd
import pytest
from app.engines.pipeline import run_preprocess
from app.engines.preprocessing import validate_dsl
from app.engines.recommender import recommend_config


@pytest.fixture()
def wide_df() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    n = 80
    return pd.DataFrame(
        {
            "patient_id": [f"P{i:03d}" for i in range(n)],
            "age": rng.uniform(20, 80, n).round(1),
            "gender": rng.choice(["男", "女"], n),
            "wbc": rng.uniform(3, 15, n).round(2),
            "os_months": rng.uniform(1, 60, n).round(1),
            "death": rng.choice([0, 1], n),
        }
    )


class TestWideRecommendation:
    def test_dsl_valid_and_runnable(self, wide_df: pd.DataFrame) -> None:
        raw = recommend_config(wide_df)
        cfg = validate_dsl(raw)  # 必须是合法 DSL
        y = wide_df["death"]
        result = run_preprocess(wide_df.drop(columns=["death"]), cfg, y=y)
        assert result.features.isna().sum().sum() == 0
        assert len(result.features) == 80

    def test_id_column_dropped(self, wide_df: pd.DataFrame) -> None:
        raw = recommend_config(wide_df)
        drops = [s for s in raw["steps"] if s["type"] == "drop_columns"]
        assert drops and "patient_id" in drops[0]["params"]["columns"]

    def test_target_time_and_event(self, wide_df: pd.DataFrame) -> None:
        raw = recommend_config(wide_df)
        assert raw["target"]["time_col"] == "os_months"
        assert raw["target"]["event_col"] == "death"
        # 事件列 0/1 → 分层
        assert raw["validation"]["strategy"] == "stratified_kfold"

    def test_categorical_missing_mode(self, wide_df: pd.DataFrame) -> None:
        raw = recommend_config(wide_df)
        missing = next(s for s in raw["steps"] if s["type"] == "missing")
        assert missing["params"]["default"] == "median"
        assert missing["params"]["per_column"].get("gender") == "mode"

    def test_seed_and_core_steps(self, wide_df: pd.DataFrame) -> None:
        raw = recommend_config(wide_df)
        assert raw["validation"]["seed"] == 42
        types = [s["type"] for s in raw["steps"]]
        for expected in ("missing", "outlier", "encode", "scale", "feature_select"):
            assert expected in types

    def test_label_only_target(self) -> None:
        df = pd.DataFrame(
            {
                "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "group": ["A", "B", "A", "B", "A", "B"],
            }
        )
        raw = recommend_config(df)
        assert raw["target"].get("label_col") == "group"
        assert "time_col" not in raw["target"] or raw["target"]["time_col"] is None


class TestLongFormatRecommendation:
    @pytest.fixture()
    def long_df(self) -> pd.DataFrame:
        rows = []
        for pid in range(1, 21):
            for item in ("白细胞计数", "血红蛋白", "血小板"):
                rows.append((f"P{pid:03d}", item, float(pid)))
        return pd.DataFrame(rows, columns=["患者ID", "检验名称", "归一化值"])

    def test_reshape_inserted_first(self, long_df: pd.DataFrame) -> None:
        raw = recommend_config(long_df)
        first = raw["steps"][0]
        assert first["type"] == "reshape"
        assert first["params"]["index"] == "患者ID"
        assert first["params"]["columns"] == "检验名称"
        assert first["params"]["values"] == "归一化值"

    def test_long_dsl_runnable(self, long_df: pd.DataFrame) -> None:
        raw = recommend_config(long_df)
        cfg = validate_dsl(raw)
        result = run_preprocess(long_df, cfg)
        assert set(result.features.columns) >= {"白细胞计数", "血红蛋白", "血小板"}
        assert len(result.features) == 20  # 一行=一个患者
        # 主键列透视后删除，不进特征
        assert "患者ID" not in result.features.columns

    def test_wide_data_no_reshape(self, wide_df: pd.DataFrame) -> None:
        raw = recommend_config(wide_df)
        assert raw["steps"][0]["type"] != "reshape"
