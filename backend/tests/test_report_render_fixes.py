"""T6.15① P0 渲染修复测试（路线图 T6.15 范围①；docs/10 §2）。

实据来源：服务器报告 report-434b9064.html 逐章解剖（2026-09-09）——
§5 p 值列出现 nan；§1 分类任务误渲染「事件数：；中位随访时间：。」空字段；
§3 预处理参数以原始 JSON + \\uXXXX 转义直出。

- p 值 nan → 「—」渲染守卫：引擎 nan 守卫（statistics._compute_pvalue）
  + 模板 fmt_num 过滤器双保险；
- §1 生存字段仅在有真实值时渲染（Jinja Undefined is not none 为真的陷阱）；
- §3 预处理参数人性化：键=值 可读格式，中文不做 \\uXXXX 转义。
"""

from typing import Any

from app.engines.comparison import statistics
from app.engines.reporting.context import build_report_context
from app.engines.reporting.render import render_html

from tests.test_report_context import _payload

NAN = float("nan")


def _render(payload: dict[str, Any]) -> str:
    return render_html(build_report_context(payload))


class TestSurvivalFieldsGuard:
    """§1 数据概况：非生存任务不得渲染生存空字段。"""

    def test_classification_no_empty_survival_fields(self) -> None:
        # _payload 为分类任务，target_summary 无 events/median_followup 键
        html = _render(_payload())
        assert "事件数：；" not in html
        assert "中位随访时间：。" not in html

    def test_regression_no_empty_survival_fields(self) -> None:
        payload = _payload()
        payload["run"]["task_type"] = "regression"
        payload["target_summary"] = {"n_samples": 92, "n_features": 5, "label_mean": 3.21}
        html = _render(payload)
        assert "事件数：；" not in html
        assert "中位随访时间：。" not in html

    def test_survival_fields_rendered_when_present(self) -> None:
        payload = _payload()
        payload["run"]["task_type"] = "survival"
        payload["target_summary"] = {
            "n_samples": 92,
            "n_features": 5,
            "events": 30,
            "median_followup": 12.5,
        }
        html = _render(payload)
        assert "事件数：30" in html
        assert "中位随访时间：12.5" in html


class TestNanPValueGuards:
    """p 值 nan 不得流入报告：引擎守卫 + 模板过滤器双保险。"""

    def test_engine_compute_pvalue_nan_returns_dash(self, monkeypatch: Any) -> None:
        """引擎层守卫：paired_t_test 异常返回 nan 时 p_value_text 为 '—'。"""
        monkeypatch.setattr(
            statistics, "paired_t_test", lambda a, b: {"p_value": NAN, "t_statistic": NAN}
        )
        p_value, text = statistics._compute_pvalue(
            [0.9, 0.8, 0.85], [0.9, 0.8, 0.85], "classification", "auc"
        )
        assert p_value is None
        assert text == "—"

    def test_screening_nan_pvalue_renders_dash(self) -> None:
        payload = _payload()
        payload["screening"] = {
            "rows": [
                {
                    "feature": "x1",
                    "test": "mannwhitney",
                    "effect": None,
                    "p_value": NAN,
                    "selected": False,
                }
            ],
            "alpha": 0.05,
            "selected_features": [],
            "n_total_tested": 1,
        }
        html = _render(payload)
        assert ">nan<" not in html

    def test_screening_nan_effect_renders_dash(self) -> None:
        payload = _payload()
        payload["screening"] = {
            "rows": [
                {
                    "feature": "x1",
                    "test": "mannwhitney",
                    "effect": NAN,
                    "p_value": 0.03,
                    "selected": True,
                }
            ],
            "alpha": 0.05,
            "selected_features": ["x1"],
            "n_total_tested": 1,
        }
        html = _render(payload)
        assert ">nan<" not in html

    def test_diagnostics_nan_pvalue_renders_dash(self) -> None:
        payload = _payload()
        payload["diagnostics"] = {
            "model_key": "rf",
            "paragraph": "",
            "coefficients": [
                {"term": "age", "coef": 0.12, "ci_lower": 0.01, "ci_upper": 0.23, "p_value": NAN}
            ],
            "shapiro": {
                "test_name": "Shapiro-Wilk",
                "statistic": 0.95,
                "p_value": NAN,
                "conclusion": "无法判定",
            },
            "breusch_pagan": {"statistic": 1.2, "p_value": 0.27, "conclusion": "未发现异方差"},
            "durbin_watson": {"statistic": 2.01, "conclusion": "无明显自相关"},
            "vif": {"vif_values": {"age": 1.1}, "conclusion": ""},
        }
        html = _render(payload)
        assert ">nan<" not in html

    def test_logrank_nan_pvalue_renders_dash(self) -> None:
        payload = _payload()
        payload["run"]["task_type"] = "survival"
        payload["survival_analysis"] = {
            "at_risk": None,
            "logrank": {
                "model_key": "coxph",
                "median_risk": 0.5,
                "n_high": 46,
                "n_low": 46,
                "statistic": 3.21,
                "p_value": NAN,
            },
        }
        html = _render(payload)
        assert "p=nan" not in html
        assert "p=—" in html

    def test_normal_pvalues_unaffected(self) -> None:
        """健康数值不受影响：筛选表真实 p 值照常格式化。"""
        payload = _payload()
        payload["screening"] = {
            "rows": [
                {
                    "feature": "x1",
                    "test": "mannwhitney",
                    "effect": 0.42,
                    "p_value": 0.0378,
                    "selected": True,
                }
            ],
            "alpha": 0.05,
            "selected_features": ["x1"],
            "n_total_tested": 1,
        }
        html = _render(payload)
        assert "0.0378" in html


class TestPreprocessParamsReadable:
    """§3 预处理参数人性化：键=值 可读格式，中文不转义。"""

    def test_params_humanized_no_unicode_escape(self) -> None:
        payload = _payload()
        payload["preprocess_steps"] = [
            {"type": "missing", "params": {"strategy": "中位数填补", "columns": ["bmi"]}}
        ]
        html = _render(payload)
        assert "strategy=中位数填补" in html
        assert "\\u4e2d" not in html  # 不得出现 \uXXXX 转义

    def test_params_default_payload_readable(self) -> None:
        html = _render(_payload())
        assert "default=median" in html
        assert '{"default": "median"}' not in html  # 不再原始 JSON 直出

    def test_params_empty_renders_dash(self) -> None:
        payload = _payload()
        payload["preprocess_steps"] = [{"type": "scale", "params": {}}]
        html = _render(payload)
        assert "<td>—</td>" in html

    def test_appendix_keeps_raw_step_count(self) -> None:
        """附录可复现信息不受影响：步骤数照常统计。"""
        html = _render(_payload())
        assert "预处理步骤数" in html
