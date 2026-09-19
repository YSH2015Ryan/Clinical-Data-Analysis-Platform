"""P0-10/P0-12 Analysis Status 状态灯与 RED 横幅测试（updateplan §69/§70）。

规则系统确定性判定（非 LLM）；RED 时报告首页醒目横幅含 §70 固定声明。
"""

from app.engines.reporting.analysis_status import compute_analysis_status
from app.engines.reporting.context import build_report_context
from app.engines.reporting.render import render_html

from tests.test_report_context import _payload
from tests.test_report_redflags import _redflag_payload


class TestStatusRules:
    def test_green_on_healthy_payload(self) -> None:
        status = compute_analysis_status(_payload())
        assert status["level"] == "GREEN"
        assert status["scope_banner"] is False

    def test_red_on_blocker_finding(self) -> None:
        payload = _payload()
        payload["integrity"] = {
            "findings": [{"severity": "blocker", "code": "TARGET_PROXY"}],
            "has_blocking_issue": True,
        }
        status = compute_analysis_status(payload)
        assert status["level"] == "RED"
        assert any("TARGET_PROXY" in r for r in status["reasons"])

    def test_red_on_critical_leakage_finding(self) -> None:
        payload = _payload()
        payload["integrity"] = {
            "findings": [{"severity": "critical", "code": "DATE_DERIVED_TARGET"}],
        }
        assert compute_analysis_status(payload)["level"] == "RED"

    def test_yellow_on_warning_finding(self) -> None:
        payload = _payload()
        payload["integrity"] = {"findings": [{"severity": "warning", "code": "NAME_SIMILARITY"}]}
        status = compute_analysis_status(payload)
        assert status["level"] == "YELLOW"
        assert status["scope_banner"] is False

    def test_red_on_quality_criticals(self) -> None:
        payload = _payload()
        payload["quality"] = {
            "status": "PASSED_WITH_WARNINGS",
            "blockers": 0,
            "warnings": 0,
            "criticals": 1,
            "issues": [],
            "column_profiles": [],
        }
        assert compute_analysis_status(payload)["level"] == "RED"

    def test_red_on_perfect_metric_redflag(self) -> None:
        assert compute_analysis_status(_redflag_payload())["level"] == "RED"

    def test_yellow_on_outcome_associated_missingness(self) -> None:
        """P1-11（§12）：Possible MNAR（缺失与结局相关）→ YELLOW 重要局限。"""
        payload = _payload()
        payload["missingness"] = {
            "alpha": 0.05,
            "variables": [
                {
                    "column": "troponin",
                    "n_missing": 40,
                    "missing_rate": 0.2,
                    "outcome_association_p": 0.001,
                    "associated_variables": [],
                    "mechanism": "possible_mnar",
                    "warning": 'WARNING: Missingness in "troponin" is associated with the outcome.',
                    "imputation_advice": "建议多重插补",
                }
            ],
            "has_outcome_associated_missingness": True,
        }
        status = compute_analysis_status(payload)
        assert status["level"] == "YELLOW"
        assert any("MNAR" in r and "troponin" in r for r in status["reasons"])

    def test_missingness_rendered_in_quality_section(self) -> None:
        payload = _payload()
        payload["missingness"] = {
            "alpha": 0.05,
            "variables": [
                {
                    "column": "troponin",
                    "n_missing": 40,
                    "missing_rate": 0.2,
                    "outcome_association_p": 0.001,
                    "associated_variables": ["age"],
                    "mechanism": "possible_mnar",
                    "warning": 'WARNING: Missingness in "troponin" is associated with the outcome.',
                    "imputation_advice": "建议多重插补",
                }
            ],
            "has_outcome_associated_missingness": True,
        }
        html = render_html(build_report_context(payload))
        assert "缺失数据机制" in html
        assert "Possible MNAR" in html
        assert "Single imputation may introduce bias" not in html  # warning 文案另测逐字
        assert "associated with the outcome" in html

    def test_epv_tiers(self) -> None:
        # _redflag_payload 基础上把指标调正常，隔离 EPV 单因素
        payload = _redflag_payload()
        payload["table"][0]["metrics"]["auc"]["mean"] = 0.85
        payload["target_summary"]["positives"] = 120  # EPV=3 → RED
        assert compute_analysis_status(payload)["level"] == "RED"
        payload["target_summary"]["positives"] = 280  # EPV=7 → YELLOW
        assert compute_analysis_status(payload)["level"] == "YELLOW"
        payload["target_summary"]["positives"] = 800  # EPV=20 → GREEN
        assert compute_analysis_status(payload)["level"] == "GREEN"


class TestStatusRendered:
    def test_red_banner_with_fixed_scope_text(self) -> None:
        html = render_html(build_report_context(_redflag_payload()))
        assert 'class="status-banner status-red"' in html
        # §70 固定声明逐字渲染（不含撇号的片段，避免 autoescape 转义干扰断言）
        for fragment in (
            "early-stage clinical research",
            "does NOT constitute medical advice",
            "must not be used to guide patient care",
        ):
            assert fragment in html
        assert "重大数据或方法学问题" in html

    def test_green_render_no_banner(self) -> None:
        html = render_html(build_report_context(_payload()))
        assert 'class="status-banner status-red"' not in html
        assert "status-green" in html  # GREEN 仍有轻量徽标

    def test_status_not_from_llm(self) -> None:
        """§69：状态由规则决定——payload 塞入 LLM 文案不影响 level。"""
        payload = _redflag_payload()
        payload["llm_note"] = "模型表现优秀，可放心临床使用"
        assert compute_analysis_status(payload)["level"] == "RED"


class TestExploratoryMode:
    """§72：用户确认在 critical 级方法学问题下继续 → 探索性模式，报告强制 RED。"""

    def test_exploratory_mode_forces_red_on_healthy_payload(self) -> None:
        payload = _payload()
        payload["run"]["exploratory_mode"] = True
        status = compute_analysis_status(payload)
        assert status["level"] == "RED"
        assert status["scope_banner"] is True
        assert any("探索性" in r for r in status["reasons"])

    def test_exploratory_fixed_sentence_verbatim(self) -> None:
        """§72 固定声明逐字输出（非 LLM 生成，不得改写）。"""
        payload = _payload()
        payload["run"]["exploratory_mode"] = True
        status = compute_analysis_status(payload)
        assert (
            status["exploratory_statement"]
            == "Results should not be interpreted as unbiased predictive performance."
        )

    def test_exploratory_false_no_effect(self) -> None:
        payload = _payload()
        payload["run"]["exploratory_mode"] = False
        assert compute_analysis_status(payload)["level"] == "GREEN"

    def test_exploratory_render_includes_fixed_sentence(self) -> None:
        payload = _payload()
        payload["run"]["exploratory_mode"] = True
        html = render_html(build_report_context(payload))
        assert 'class="status-banner status-red"' in html
        assert "Results should not be interpreted as unbiased predictive performance" in html
