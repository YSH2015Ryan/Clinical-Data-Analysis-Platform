"""P2-1 EDA 引擎测试（engines/eda.py，docs/08 §3.2 阶段 A）。

契约：纯计算、确定性（无随机）、全部统计量可溯源；不依赖 DB/网络。
"""

import numpy as np
import pandas as pd
from app.engines.eda import compute_eda


def _df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 200
    age = rng.normal(60, 10, n)
    gender = np.where(np.arange(n) % 2 == 0, "男", "女")
    death = (age > 62).astype(int)
    df = pd.DataFrame({"age": age, "gender": gender, "death": death})
    df.loc[df.index[:20], "age"] = np.nan  # 10% 缺失
    return df


_PROFILES = [
    {
        "name": "age",
        "inferred_type": "continuous",
        "semantic": "Age",
        "semantic_confidence": 0.9,
        "missing_rate": 0.1,
        "unique": 180,
    },
    {
        "name": "gender",
        "inferred_type": "categorical",
        "semantic": "Gender",
        "semantic_confidence": 0.9,
        "missing_rate": 0.0,
        "unique": 2,
    },
    {
        "name": "death",
        "inferred_type": "continuous",
        "semantic": "Event",
        "semantic_confidence": 0.9,
        "missing_rate": 0.0,
        "unique": 2,
        "min": 0.0,
        "max": 1.0,
    },
]


class TestDistributions:
    def test_continuous_histogram_sums_to_non_null(self) -> None:
        eda = compute_eda(_df(), _PROFILES)
        age = next(d for d in eda["distributions"] if d["name"] == "age")
        assert age["kind"] == "continuous"
        assert sum(age["histogram"]["counts"]) == 180
        assert len(age["histogram"]["counts"]) == len(age["histogram"]["bin_edges"]) - 1
        # 扩展统计量（P2-1：均值/SD/分位数/偏度）
        assert abs(age["stats"]["mean"] - np.nanmean(_df()["age"])) < 1e-6
        assert age["stats"]["std"] > 0
        assert "q1" in age["stats"] and "q3" in age["stats"] and "skew" in age["stats"]

    def test_categorical_top_counts(self) -> None:
        eda = compute_eda(_df(), _PROFILES)
        gender = next(d for d in eda["distributions"] if d["name"] == "gender")
        assert gender["kind"] == "categorical"
        counts = {c["value"]: c["count"] for c in gender["top_counts"]}
        assert counts == {"男": 100, "女": 100}

    def test_missing_excluded_from_histogram(self) -> None:
        df = _df()
        eda = compute_eda(df, _PROFILES)
        age = next(d for d in eda["distributions"] if d["name"] == "age")
        assert age["missing"] == 20


class TestMissingness:
    def test_rates_and_complete_cases(self) -> None:
        eda = compute_eda(_df(), _PROFILES)
        m = eda["missing"]
        rates = {r["name"]: r["missing_rate"] for r in m["columns"]}
        assert abs(rates["age"] - 0.1) < 1e-9
        assert rates["gender"] == 0.0
        assert m["complete_case_ratio"] == 0.9
        assert m["rows_with_any_missing"] == 20


class TestCorrelations:
    def test_pearson_matrix_identity_diagonal(self) -> None:
        eda = compute_eda(_df(), _PROFILES)
        corr = eda["correlations"]["continuous"]
        cols = corr["columns"]
        assert "age" in cols
        idx = cols.index("age")
        assert abs(corr["matrix"][idx][idx] - 1.0) < 1e-9

    def test_cramers_v_categorical_pairs(self) -> None:
        df = _df()
        df["smoke"] = np.where(df["gender"] == "男", "是", "否")  # 完全相关
        profiles = [
            *_PROFILES,
            {
                "name": "smoke",
                "inferred_type": "categorical",
                "semantic": None,
                "semantic_confidence": 0.0,
                "missing_rate": 0.0,
                "unique": 2,
            },
        ]
        eda = compute_eda(df, profiles)
        cat = eda["correlations"]["categorical"]
        pairs = {(p["a"], p["b"]): p["cramers_v"] for p in cat["top_pairs"]}
        key = ("gender", "smoke") if ("gender", "smoke") in pairs else ("smoke", "gender")
        assert abs(pairs[key] - 1.0) < 1e-6

    def test_top_pairs_sorted(self) -> None:
        eda = compute_eda(_df(), _PROFILES)
        pairs = eda["correlations"]["continuous"]["top_pairs"]
        vals = [abs(p["r"]) for p in pairs]
        assert vals == sorted(vals, reverse=True)


class TestSampleSize:
    def test_epv_with_event_column(self) -> None:
        eda = compute_eda(_df(), _PROFILES)
        ss = eda["sample_size"]
        assert ss["n_rows"] == 200
        assert ss["n_events"] == int(_df()["death"].sum())
        assert ss["event_column"] == "death"
        # EPV = 事件数 / 候选特征数（排除结局列本身）
        assert abs(ss["epv"] - ss["n_events"] / 2) < 1e-9

    def test_no_event_column(self) -> None:
        df = _df().drop(columns=["death"])
        profiles = [p for p in _PROFILES if p["name"] != "death"]
        eda = compute_eda(df, profiles)
        ss = eda["sample_size"]
        assert ss["n_events"] is None and ss["epv"] is None

    def test_epv_level_three_tiers(self) -> None:
        """P0-11（updateplan §19）：EPV ≥10 ok / 5–10 warning / <5 critical。"""
        profiles = [
            {"name": "death", "inferred_type": "continuous", "semantic": "Event",
             "semantic_confidence": 0.9, "missing_rate": 0.0, "unique": 2},
        ] + [
            {"name": f"x{i}", "inferred_type": "continuous", "semantic": None,
             "semantic_confidence": 0.0, "missing_rate": 0.0, "unique": 100}
            for i in range(4)
        ]
        # n_features=4：事件数 40 → EPV=10(ok)；28 → 7(warning)；12 → 3(critical)
        for n_events, expected in ((40, "ok"), (28, "warning"), (12, "critical")):
            n = 200
            death = np.array([1] * n_events + [0] * (n - n_events))
            df = pd.DataFrame({"death": death, **{f"x{i}": np.arange(n) for i in range(4)}})
            ss = compute_eda(df, profiles)["sample_size"]
            assert ss["epv"] == round(n_events / 4, 2)
            assert ss["epv_level"] == expected

    def test_epv_level_none_without_event_column(self) -> None:
        df = _df().drop(columns=["death"])
        profiles = [p for p in _PROFILES if p["name"] != "death"]
        ss = compute_eda(df, profiles)["sample_size"]
        assert ss["epv_level"] is None


class TestRobustness:
    def test_empty_df(self) -> None:
        eda = compute_eda(pd.DataFrame(), [])
        assert eda["row_count"] == 0
        assert eda["distributions"] == []

    def test_single_column(self) -> None:
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        profiles = [
            {
                "name": "x",
                "inferred_type": "continuous",
                "semantic": None,
                "semantic_confidence": 0.0,
                "missing_rate": 0.0,
                "unique": 3,
            }
        ]
        eda = compute_eda(df, profiles)
        assert eda["correlations"]["continuous"]["columns"] == ["x"]

    def test_json_serializable(self) -> None:
        import json

        json.dumps(compute_eda(_df(), _PROFILES))  # 不抛异常（numpy 类型已转换）

    def test_deterministic(self) -> None:
        a = compute_eda(_df(), _PROFILES)
        b = compute_eda(_df(), _PROFILES)
        assert a == b
