"""P3 生存补充统计单测（engines/reporting/survival_extra.py；docs/19）。

- at_risk_table：各时间点风险集人数来自真实 times 计数，单调不增；
- median_risk_logrank：按 OOF 风险中位分层的 log-rank 检验（lifelines 真实计算）。
"""

import numpy as np

from app.engines.reporting.survival_extra import at_risk_table, median_risk_logrank


class TestAtRiskTable:
    def test_counts_from_real_times(self) -> None:
        times = [1.0, 2.0, 3.0, 4.0, 5.0]
        events = [1, 1, 1, 0, 0]
        out = at_risk_table(times, events, points=[0.0, 2.5, 5.0])
        assert out["times"] == [0.0, 2.5, 5.0]
        assert out["at_risk"] == [5, 3, 1]
        assert out["events_cum"] == [0, 2, 3]

    def test_default_points_and_monotonic(self) -> None:
        rng = np.random.default_rng(42)
        times = rng.uniform(1, 100, 80).tolist()
        events = rng.integers(0, 2, 80).tolist()
        out = at_risk_table(times, events)
        assert len(out["times"]) == len(out["at_risk"]) == len(out["events_cum"])
        assert all(b <= a for a, b in zip(out["at_risk"], out["at_risk"][1:]))
        assert out["at_risk"][0] == 80

    def test_empty_input(self) -> None:
        assert at_risk_table([], []) is None


class TestMedianRiskLogrank:
    def test_separated_groups_significant(self) -> None:
        rng = np.random.default_rng(42)
        n = 200
        # 高风险组事件早、低风险组事件晚 → log-rank 应显著
        risks = np.concatenate([np.zeros(n // 2), np.ones(n // 2)])
        times = np.concatenate([rng.uniform(1, 10, n // 2), rng.uniform(30, 60, n // 2)])
        events = np.ones(n, dtype=int)
        out = median_risk_logrank(times, events, risks)
        assert out is not None
        assert out["n_high"] == n // 2 and out["n_low"] == n // 2
        assert out["p_value"] < 0.05
        assert out["statistic"] > 0
        assert 0.0 <= out["median_risk"] <= 1.0

    def test_identical_risks_returns_none(self) -> None:
        times = [float(i) for i in range(1, 11)]
        events = [1] * 10
        assert median_risk_logrank(times, events, [0.5] * 10) is None

    def test_too_few_events_returns_none(self) -> None:
        times = [float(i) for i in range(1, 11)]
        events = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1]  # 仅 2 事件
        risks = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.7, 0.75, 0.8, 0.9]
        assert median_risk_logrank(times, events, risks) is None

    def test_length_mismatch_returns_none(self) -> None:
        out = median_risk_logrank([1.0, 2.0], [1, 1], [0.1])
        assert out is None
