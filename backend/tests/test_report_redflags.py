"""T6.15② 完美指标红旗测试（路线图 T6.15 范围②；科学诚实 P0）。

实据：服务器报告 report-434b9064.html —— n=92、40 变量、EPV=0.7、
三模型 AUC=1.0000（教科书级过拟合/疑似数据泄漏），结论章照常推荐无警示。

触发规则：EPV<10 且主指标交叉验证均值≥0.99（双条件缺一不可）。
触发后：limitations 动态条目置顶 + 结论章醒目警示 + 推荐措辞降级，
并点名 Top1 特征提示核查结局代理变量（引用真实特征名，不做因果断言）。
红旗只改措辞与新增警示，不改排名数值。
"""

from typing import Any

from app.engines.reporting.context import build_report_context
from app.engines.reporting.redflags import detect_perfect_metric_redflag
from app.engines.reporting.render import render_html

from tests.test_report_context import _payload


def _redflag_payload() -> dict[str, Any]:
    """复刻实据场景：EPV=0.7（28 阳性/40 变量）+ Top1 AUC=1.0000。"""
    payload = _payload()
    payload["target_summary"] = {
        "n_samples": 92,
        "n_features": 40,
        "positives": 28,
        "prevalence": 0.304,
    }
    payload["table"] = [
        {
            "model_key": "catboost",
            "status": "SUCCESS",
            "metrics": {"auc": {"mean": 1.0, "std": 0.0}},
        },
        {"model_key": "rf", "status": "SUCCESS", "metrics": {"auc": {"mean": 1.0, "std": 0.0}}},
    ]
    payload["comparison"]["ranking"] = ["catboost", "rf"]
    payload["comparison"]["recommendation"]["top"] = [
        {"model_key": "catboost", "rank": 1, "reason": "主指标最高（auc=1.0000±0.0000）"}
    ]
    payload["comparison"]["charts"] = [
        {
            "kind": "feature_importance",
            "title": "特征重要性对比",
            "data": {"features": ["出院诊断编码"], "series": []},
        }
    ]
    return payload


class TestDetectRedFlag:
    def test_triggers_on_epv_low_and_metric_perfect(self) -> None:
        flag = detect_perfect_metric_redflag(_redflag_payload())
        assert flag is not None
        assert flag["epv"] == 0.7  # 28/40，真实计算
        assert flag["metric"] == "auc"
        assert flag["metric_value"] == 1.0
        assert flag["model_key"] == "catboost"
        assert flag["top_feature"] == "出院诊断编码"  # 引用真实特征名

    def test_not_triggered_on_healthy_payload(self) -> None:
        # _payload：EPV=96/8=12，Top1 auc=0.87
        assert detect_perfect_metric_redflag(_payload()) is None

    def test_not_triggered_when_epv_low_but_metric_normal(self) -> None:
        payload = _redflag_payload()
        payload["table"][0]["metrics"]["auc"]["mean"] = 0.95
        assert detect_perfect_metric_redflag(payload) is None

    def test_not_triggered_when_metric_perfect_but_epv_ok(self) -> None:
        payload = _redflag_payload()
        payload["target_summary"]["positives"] = 800  # EPV=20
        assert detect_perfect_metric_redflag(payload) is None

    def test_threshold_boundary_not_triggered(self) -> None:
        payload = _redflag_payload()
        payload["table"][0]["metrics"]["auc"]["mean"] = 0.989  # <0.99
        assert detect_perfect_metric_redflag(payload) is None

    def test_regression_task_no_crash_no_flag(self) -> None:
        payload = _redflag_payload()
        payload["run"]["task_type"] = "regression"
        payload["target_summary"] = {"n_samples": 92, "n_features": 40, "label_mean": 3.2}
        assert detect_perfect_metric_redflag(payload) is None

    def test_missing_comparison_no_crash(self) -> None:
        payload = _redflag_payload()
        payload["comparison"] = None
        payload["table"] = None
        assert detect_perfect_metric_redflag(payload) is None

    def test_no_feature_importance_chart_top_feature_none(self) -> None:
        payload = _redflag_payload()
        payload["comparison"]["charts"] = []
        flag = detect_perfect_metric_redflag(payload)
        assert flag is not None
        assert flag["top_feature"] is None


class TestRedFlagInContext:
    def test_limitations_first_item_is_redflag(self) -> None:
        ctx = build_report_context(_redflag_payload())
        limitations = next(s for s in ctx["sections"] if s["key"] == "limitations")
        first = limitations["data"]["items"][0]
        assert "0.7" in first  # 真实 EPV
        assert "1.0" in first or "1.00" in first  # 真实指标值
        assert "过拟合" in first or "泄漏" in first

    def test_conclusion_carries_redflag_warning(self) -> None:
        ctx = build_report_context(_redflag_payload())
        conclusion = next(s for s in ctx["sections"] if s["key"] == "conclusion")
        warning = conclusion["data"].get("red_flag")
        assert warning
        assert "疑似过拟合" in warning or "数据泄漏" in warning
        assert "必须核查" in warning
        assert "出院诊断编码" in warning  # 点名 Top1 特征
        assert "0.7" in warning and "1.0" in warning  # 真实数值
        # 排名/推荐数值不改：原结论仍在
        assert "catboost" in conclusion["data"]["text"]

    def test_healthy_payload_no_redflag(self) -> None:
        ctx = build_report_context(_payload())
        conclusion = next(s for s in ctx["sections"] if s["key"] == "conclusion")
        assert conclusion["data"].get("red_flag") is None
        limitations = next(s for s in ctx["sections"] if s["key"] == "limitations")
        assert not any("过拟合/数据泄漏" in item for item in limitations["data"]["items"])


class TestRedFlagRendered:
    def test_warning_rendered_prominently(self) -> None:
        html = render_html(build_report_context(_redflag_payload()))
        assert 'class="red-flag"' in html
        assert "疑似过拟合" in html
        assert "出院诊断编码" in html
        assert "推荐模型 catboost" in html  # 原推荐保留但措辞降级由警示承担

    def test_healthy_render_no_redflag_block(self) -> None:
        html = render_html(build_report_context(_payload()))
        assert 'class="red-flag"' not in html
