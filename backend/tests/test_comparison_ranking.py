"""T6.3 排名与推荐理由模板引擎单测（docs/09 §4；docs/18 T6.3 DoD）。

- 排名规则：已知指标 → 断言排名顺序（加权公式手工核算）；
- 理由快照：只引用真实指标值，结论性措辞依赖跨模型差异；
- 方向感知：rmse/brier/ibs 越低越好，auc/c_index/r2 越高越好。
"""

import pytest
from app.engines.comparison.ranking import build_recommendation, rank_models


def _row(key: str, **metrics: tuple[float, float]) -> dict:
    return {
        "model_key": key,
        "metrics": {name: {"mean": m, "std": s} for name, (m, s) in metrics.items()},
    }


CLF_ROWS = [
    _row("a", auc=(0.9, 0.01), brier=(0.10, 0.0)),
    _row("b", auc=(0.8, 0.02), brier=(0.20, 0.0)),
    _row("c", auc=(0.7, 0.05), brier=(0.30, 0.0)),
]


class TestRankingRule:
    def test_weighted_score_order(self) -> None:
        """手工核算：a=1.0, b=0.6×0.5+0.2×0.75+0.2×0.5=0.55, c=0.0。"""
        ranked = rank_models("classification", CLF_ROWS)
        assert [m.model_key for m in ranked] == ["a", "b", "c"]
        assert ranked[0].score == pytest.approx(1.0)
        assert ranked[1].score == pytest.approx(0.55)
        assert ranked[2].score == pytest.approx(0.0)
        assert [m.rank for m in ranked] == [1, 2, 3]
        assert ranked[0].components == {"primary": 1.0, "stability": 1.0, "secondary": 1.0}

    def test_rmse_lower_is_better(self) -> None:
        rows = [
            _row("x", rmse=(2.0, 0.1), r2=(0.9, 0.0)),
            _row("y", rmse=(4.0, 0.3), r2=(0.5, 0.0)),
        ]
        ranked = rank_models("regression", rows)
        assert [m.model_key for m in ranked] == ["x", "y"]
        assert ranked[0].score == pytest.approx(1.0)

    def test_survival_ibs_lower_is_better(self) -> None:
        rows = [
            _row("p", c_index=(0.7, 0.02), ibs=(0.25, 0.0)),
            _row("q", c_index=(0.7, 0.02), ibs=(0.10, 0.0)),
        ]
        ranked = rank_models("survival", rows)
        assert ranked[0].model_key == "q"  # 主指标/稳定性并列 → ibs 决定

    def test_ties_normalize_to_one_and_stable_order(self) -> None:
        rows = [
            _row("m2", auc=(0.8, 0.02), brier=(0.1, 0.0)),
            _row("m1", auc=(0.8, 0.02), brier=(0.1, 0.0)),
        ]
        ranked = rank_models("classification", rows)
        assert all(m.score == pytest.approx(1.0) for m in ranked)
        assert [m.model_key for m in ranked] == ["m1", "m2"]  # 得分并列按 key 稳定排序

    def test_missing_secondary_scores_zero(self) -> None:
        rows = [
            _row("a", auc=(0.9, 0.01), brier=(0.1, 0.0)),
            _row("b", auc=(0.9, 0.01)),  # 缺 brier
        ]
        ranked = rank_models("classification", rows)
        b = next(m for m in ranked if m.model_key == "b")
        assert b.components["secondary"] == 0.0
        assert b.secondary_mean is None

    def test_missing_primary_ranked_last(self) -> None:
        """缺主指标的模型（如 dummy 基线）不参与加权、沉底，理由如实说明。"""
        rows = [
            _row("dummy", accuracy=(0.6, 0.0)),
            _row("a", auc=(0.9, 0.01), brier=(0.1, 0.0)),
        ]
        ranked = rank_models("classification", rows)
        assert [m.model_key for m in ranked] == ["a", "dummy"]
        assert ranked[1].primary_mean is None
        assert ranked[1].score == 0.0
        rec = build_recommendation("classification", rows)
        assert rec["top"][0]["reason"] == "主指标最高（auc=0.9000±0.0100）"
        assert rec["not_recommended"] == [{"model_key": "dummy", "reason": "缺少主指标（auc）"}]

    def test_empty_rows(self) -> None:
        assert rank_models("classification", []) == []

    def test_weights_override_changes_order(self) -> None:
        """权重全压稳定性 → 波动最小者居首（docs/09 §4.1 权重存配置）。"""
        rows = [
            _row("sharp", auc=(0.9, 0.10), brier=(0.1, 0.0)),
            _row("steady", auc=(0.8, 0.01), brier=(0.2, 0.0)),
        ]
        default = rank_models("classification", rows)
        assert default[0].model_key == "sharp"
        custom = rank_models(
            "classification", rows, weights={"primary": 0.0, "stability": 1.0, "secondary": 0.0}
        )
        assert custom[0].model_key == "steady"


class TestRecommendation:
    def test_reasons_snapshot(self) -> None:
        """理由只引用真实指标值（快照测试，docs/09 §4.2）。"""
        rec = build_recommendation("classification", CLF_ROWS)
        assert rec["ranking"] == ["a", "b", "c"]
        assert rec["top"] == [
            {
                "model_key": "a",
                "rank": 1,
                "reason": (
                    "主指标最高（auc=0.9000±0.0100），校准/拟合优度最优（brier=0.1000），"
                    "交叉验证最稳定（std=0.0100）"
                ),
            },
            {
                "model_key": "b",
                "rank": 2,
                "reason": "主指标接近首位（auc=0.8000±0.0200，差距 0.1000）",
            },
            {
                "model_key": "c",
                "rank": 3,
                "reason": "综合得分第 3 位（score=0.0000，auc=0.7000±0.0500）",
            },
        ]
        assert rec["not_recommended"] == [{"model_key": "c", "reason": "主指标最弱（auc=0.7000）"}]
        assert rec["primary_metric"] == "auc"
        assert rec["formula"] == (
            "score = 0.6×主指标归一化 + 0.2×稳定性归一化 + 0.2×次级指标归一化（docs/09 §4.1）"
        )
        assert [s["model_key"] for s in rec["scores"]] == ["a", "b", "c"]

    def test_reasons_only_real_values(self) -> None:
        """理由中出现的每个小数都必须来自输入指标快照或其差值（不虚构）。"""
        import re

        rec = build_recommendation("classification", CLF_ROWS)
        real = {
            f"{v:.4f}"
            for row in CLF_ROWS
            for entry in row["metrics"].values()
            for v in (entry["mean"], entry["std"])
        }
        real |= {f"{s['score']:.4f}" for s in rec["scores"]}
        means = [row["metrics"]["auc"]["mean"] for row in CLF_ROWS]
        real |= {f"{abs(a - b):.4f}" for a in means for b in means}  # 差距 delta
        for item in rec["top"] + rec["not_recommended"]:
            for number in re.findall(r"\d+\.\d+", item["reason"]):
                assert number in real, f"理由中出现非指标数字 {number}: {item['reason']}"

    def test_no_merit_clauses_when_tied(self) -> None:
        """全部并列 → 无「最优/最稳定」结论性措辞，not_recommended 为空。"""
        rows = [
            _row("m1", auc=(0.8, 0.02), brier=(0.1, 0.0)),
            _row("m2", auc=(0.8, 0.02), brier=(0.1, 0.0)),
        ]
        rec = build_recommendation("classification", rows)
        assert rec["top"][0]["reason"] == "主指标最高（auc=0.8000±0.0200）"
        assert rec["not_recommended"] == []

    def test_single_model_no_not_recommended(self) -> None:
        rec = build_recommendation(
            "classification", [_row("solo", auc=(0.8, 0.02), brier=(0.1, 0.0))]
        )
        assert rec["ranking"] == ["solo"]
        assert rec["not_recommended"] == []

    def test_not_recommended_weakest_component(self) -> None:
        """末位模型最弱分量为稳定性 → 理由引用真实 std。"""
        rows = [
            _row("a", auc=(0.9, 0.01), brier=(0.1, 0.0)),
            _row("b", auc=(0.9, 0.05), brier=(0.1, 0.0)),
        ]
        rec = build_recommendation("classification", rows)
        assert rec["not_recommended"] == [
            {"model_key": "b", "reason": "交叉验证波动最大（std=0.0500）"}
        ]
