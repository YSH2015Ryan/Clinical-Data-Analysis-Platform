"""P3 动态局限性清单单测（engines/reporting/limitations.py；docs/19）。

- 静态基础条目恒在；动态条目全部由 payload 真实统计触发；
- 不虚构数值：触发阈值判断只引用 payload 中已有的真实计算值。
"""

from app.engines.reporting.limitations import STATIC_LIMITATIONS, build_limitations


def _payload(**overrides):
    payload = {
        "run": {"task_type": "classification"},
        "target_summary": {"n_samples": 500, "n_features": 8, "positives": 250, "prevalence": 0.5},
        "transform_log": [],
        "quality_report": {"column_profiles": []},
    }
    payload.update(overrides)
    return payload


class TestStaticBase:
    def test_static_items_always_present(self) -> None:
        items = build_limitations(_payload())
        for static in STATIC_LIMITATIONS:
            assert static in items

    def test_no_dynamic_when_healthy(self) -> None:
        items = build_limitations(_payload())
        assert len(items) == len(STATIC_LIMITATIONS)


class TestDynamicTriggers:
    def test_class_imbalance_low_prevalence(self) -> None:
        items = build_limitations(
            _payload(target_summary={"n_samples": 500, "n_features": 8, "positives": 20, "prevalence": 0.04})
        )
        assert any("不均衡" in i and "4.0%" in i for i in items)

    def test_class_imbalance_high_prevalence(self) -> None:
        items = build_limitations(
            _payload(target_summary={"n_samples": 500, "n_features": 8, "positives": 480, "prevalence": 0.96})
        )
        assert any("不均衡" in i for i in items)

    def test_epv_below_10(self) -> None:
        items = build_limitations(
            _payload(target_summary={"n_samples": 200, "n_features": 10, "positives": 30, "prevalence": 0.15})
        )
        assert any("EPV" in i and "3.0" in i for i in items)

    def test_survival_few_events(self) -> None:
        items = build_limitations(
            _payload(
                run={"task_type": "survival"},
                target_summary={"n_samples": 300, "n_features": 5, "events": 40, "median_followup": 12.0},
            )
        )
        assert any("事件数" in i and "40" in i for i in items)

    def test_small_sample(self) -> None:
        items = build_limitations(
            _payload(target_summary={"n_samples": 120, "n_features": 5, "positives": 60, "prevalence": 0.5})
        )
        assert any("样本量" in i and "120" in i for i in items)

    def test_auto_fix_transform_log(self) -> None:
        items = build_limitations(
            _payload(transform_log=[{"action": "impute_missing", "column": "bmi"}])
        )
        assert any("自动修复" in i and "1" in i for i in items)

    def test_high_missing_rate_column(self) -> None:
        items = build_limitations(
            _payload(
                quality_report={
                    "column_profiles": [{"name": "bmi", "missing_rate": 0.3}],
                }
            )
        )
        assert any("bmi" in i and "缺失" in i and "30.0%" in i for i in items)

    def test_missing_target_summary_safe(self) -> None:
        payload = _payload()
        del payload["target_summary"]
        items = build_limitations(payload)
        assert len(items) == len(STATIC_LIMITATIONS)
