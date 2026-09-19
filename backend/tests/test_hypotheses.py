"""P2-06 Hypothesis Generation + §81 Research Opportunities（先行测试）。

确定性规则从体检真实事实（EDA 相关对/样本量/缺失/不均衡、列画像、研究画像、
缺口建议）生成五类研究机会：Observed Patterns / Unexpected Associations /
Potential Subgroup Differences / Potential Prediction Tasks / Potential Hypotheses。
全部条目附真实数值 basis；统一 Hypothesis-generating 标记；禁止「Novel Finding」
式措辞（Principle 6）。
"""

from typing import Any

import pandas as pd
from app.engines.hypotheses import generate_research_opportunities


def _df(n: int = 400) -> pd.DataFrame:
    """合成数据：age/bmi 连续且强相关(r≈0.99 构造)、sex 二分类、outcome 二值结局。"""
    import numpy as np

    rng = np.random.default_rng(6)
    age = rng.normal(60, 10, n)
    bmi = age * 0.4 + rng.normal(0, 0.5, n)  # 与 age 强相关
    sex = rng.choice(["M", "F"], n)
    ward = rng.choice(["A", "B", "C"], n)
    outcome = (rng.uniform(0, 1, n) < 0.3).astype(int)
    return pd.DataFrame({"age": age, "bmi": bmi, "sex": sex, "ward": ward, "outcome": outcome})


def _inputs(df: pd.DataFrame) -> dict[str, Any]:
    """真实管线：validation → eda → profiler → supplement，与 insight_tasks 同源。"""
    from app.engines import validation
    from app.engines.eda import compute_eda
    from app.engines.research_profiler import detect_research_direction
    from app.engines.supplement_advisor import advise_supplements

    report = validation.validate(df, raw_columns=[str(c) for c in df.columns])
    eda = compute_eda(df, report.column_profiles)
    research = detect_research_direction(df)
    plan = advise_supplements(df, eda, report.column_profiles, research)
    return {
        "df": df,
        "eda": eda,
        "column_profiles": report.column_profiles,
        "research_profile": research,
        "supplement_plan": plan,
    }


class TestContract:
    def test_five_categories_and_banner(self) -> None:
        result = generate_research_opportunities(**_inputs(_df()))
        assert result["hypothesis_generating"] is True
        assert "Hypothesis-generating" in result["notice"]
        for key in (
            "observed_patterns",
            "unexpected_associations",
            "potential_subgroup_differences",
            "potential_prediction_tasks",
            "potential_hypotheses",
        ):
            assert isinstance(result[key], list)
        assert result["llm_summary"] is None  # 规则保底；LLM 槽位预留

    def test_no_overclaim_wording(self) -> None:
        """Principle 6：不得出现 Novel Finding / Guaranteed Publishable 类措辞。"""
        import json

        result = generate_research_opportunities(**_inputs(_df()))
        text = json.dumps(result, ensure_ascii=False)
        for banned in ("Novel Finding", "Guaranteed Publishable", "首次发现", "保证可发表"):
            assert banned not in text

    def test_items_have_basis(self) -> None:
        result = generate_research_opportunities(**_inputs(_df()))
        for key in ("observed_patterns", "unexpected_associations", "potential_hypotheses"):
            for item in result[key]:
                assert item["text"] and item["basis"]

    def test_deterministic(self) -> None:
        inputs = _inputs(_df())
        assert generate_research_opportunities(**inputs) == generate_research_opportunities(
            **inputs
        )


class TestObservedPatterns:
    def test_strong_correlation_reported_with_real_r(self) -> None:
        """age/bmi 构造 r≈0.99 → observed_patterns 引用真实 r 值。"""
        inputs = _inputs(_df())
        result = generate_research_opportunities(**inputs)
        pair = next(
            (p for p in result["observed_patterns"] if "age" in p["text"] and "bmi" in p["text"]),
            None,
        )
        assert pair is not None
        real_r = next(
            p["r"]
            for p in inputs["eda"]["correlations"]["continuous"]["top_pairs"]
            if {p["a"], p["b"]} == {"age", "bmi"}
        )
        assert f"{real_r:.2f}" in pair["basis"]


class TestSubgroupsAndTasks:
    def test_categorical_candidates(self) -> None:
        """sex/ward（2-6 水平分类列）成为候选亚组变量；结局列排除。"""
        result = generate_research_opportunities(**_inputs(_df()))
        sub_vars = [i["variable"] for i in result["potential_subgroup_differences"]]
        assert "sex" in sub_vars and "ward" in sub_vars
        assert "outcome" not in sub_vars

    def test_prediction_tasks_from_profile(self) -> None:
        result = generate_research_opportunities(**_inputs(_df()))
        assert result["potential_prediction_tasks"]  # 二值结局 → 至少一个预测任务方向


class TestEdgeCases:
    def test_minimal_df_no_crash(self) -> None:
        df = pd.DataFrame({"x": [1, 2, 3], "y": [0, 1, 0]})
        result = generate_research_opportunities(**_inputs(df))
        assert result["hypothesis_generating"] is True

    def test_no_correlations_empty_lists(self) -> None:
        """无连续列 → 相关类清单为空而非报错。"""
        df = pd.DataFrame({"g": ["a", "b", "a", "b"], "outcome": [0, 1, 0, 1]})
        result = generate_research_opportunities(**_inputs(df))
        assert result["observed_patterns"] == [] or all(
            "r=" not in p["basis"] for p in result["observed_patterns"]
        )
