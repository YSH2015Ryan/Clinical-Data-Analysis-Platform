"""P2-07 AI Evidence Binding（updateplan §55，先行测试）。

LLM/规则生成的每一条结论（claim）必须绑定结构化证据：
证据注册表由报告 payload 中真实计算的指标/图表/表格/样本事实构建；
claim 引用不存在的证据或引用值与真实值不符 → blocked（红线 8，§56 Reject）。
"""

from typing import Any

from app.engines.evidence_binding import (
    bind_claim,
    build_evidence_registry,
    validate_claims,
)


def _payload(**over: Any) -> dict[str, Any]:
    """模拟 assemble_report_payload 输出形状。"""
    base: dict[str, Any] = {
        "table": [
            {
                "model_key": "logistic_regression",
                "metrics": {
                    "roc_auc": {"mean": 0.91, "std": 0.02},
                    "pr_auc": {"mean": 0.83, "std": 0.03},
                },
            },
            {
                "model_key": "xgboost",
                "metrics": {"roc_auc": {"mean": 0.88, "std": 0.04}},
            },
        ],
        "comparison": {
            "charts": [
                {"kind": "roc", "title": "ROC 曲线"},
                {"kind": "calibration", "title": "校准曲线"},
            ]
        },
        "target_summary": {"n_samples": 400, "prevalence": 0.3, "events": 120},
        "screening": {
            "rows": [
                {"variable": "age", "p_value": 0.032, "p_adjusted": 0.048},
                {"variable": "bmi", "p_value": 0.8, "p_adjusted": None},
            ]
        },
        "calibration": {"hosmer_lemeshow": {"p_value": 0.42}},
    }
    base.update(over)
    return base


class TestRegistry:
    def test_metric_entries_real_values(self) -> None:
        reg = build_evidence_registry(_payload())
        e = reg["metric:logistic_regression:roc_auc"]
        assert e["kind"] == "metric"
        assert e["value"] == 0.91 and e["std"] == 0.02  # 与 payload 完全一致，不编造
        assert reg["metric:xgboost:roc_auc"]["value"] == 0.88

    def test_figure_entries(self) -> None:
        reg = build_evidence_registry(_payload())
        assert reg["figure:roc"]["kind"] == "figure"
        assert reg["figure:calibration"]["title"] == "校准曲线"

    def test_fact_and_table_entries(self) -> None:
        reg = build_evidence_registry(_payload())
        assert reg["fact:target_summary:n_samples"]["value"] == 400
        assert reg["fact:target_summary:prevalence"]["value"] == 0.3
        # 筛选行优先引用校正后 p（§30）；无校正值回退原始 p
        assert reg["table:screening:age"]["value"] == 0.048
        assert reg["table:screening:bmi"]["value"] == 0.8
        assert reg["metric:calibration:hosmer_lemeshow_p"]["value"] == 0.42

    def test_none_values_skipped(self) -> None:
        reg = build_evidence_registry(_payload(target_summary={"n_samples": 400, "events": None}))
        assert "fact:target_summary:events" not in reg

    def test_empty_payload_no_crash(self) -> None:
        assert build_evidence_registry({}) == {}

    def test_deterministic(self) -> None:
        assert build_evidence_registry(_payload()) == build_evidence_registry(_payload())


class TestBindAndValidate:
    def test_supported_claim_exact_value(self) -> None:
        reg = build_evidence_registry(_payload())
        claim = bind_claim(
            "模型区分度良好", "metric:logistic_regression:roc_auc", reg, quoted_value=0.91
        )
        assert claim["supported"] is True
        assert claim["evidence"]["value"] == 0.91  # §55：claim 携带结构化证据

    def test_quoted_value_mismatch_blocked(self) -> None:
        """§56：引用值与真实计算值不符 → Reject。"""
        reg = build_evidence_registry(_payload())
        claim = bind_claim(
            "模型区分度优秀", "metric:logistic_regression:roc_auc", reg, quoted_value=0.99
        )
        assert claim["supported"] is False
        assert claim["reason"] == "value_mismatch"

    def test_rounding_tolerance_allowed(self) -> None:
        """5% 相对容差内（如 0.909 引述 0.91）不误杀。"""
        reg = build_evidence_registry(_payload())
        claim = bind_claim("d", "metric:logistic_regression:roc_auc", reg, quoted_value=0.909)
        assert claim["supported"] is True

    def test_unknown_evidence_blocked(self) -> None:
        reg = build_evidence_registry(_payload())
        claim = bind_claim("d", "metric:nonexistent:roc_auc", reg)
        assert claim["supported"] is False
        assert claim["reason"] == "evidence_not_found"

    def test_figure_claim_with_value_blocked(self) -> None:
        """图表类证据无数值；引用数值 → blocked（数值必须来自 metric/fact/table 证据）。"""
        reg = build_evidence_registry(_payload())
        no_val = bind_claim("见 ROC 曲线", "figure:roc", reg)
        assert no_val["supported"] is True
        with_val = bind_claim("AUC 0.91", "figure:roc", reg, quoted_value=0.91)
        assert with_val["supported"] is False
        assert with_val["reason"] == "no_numeric_value"

    def test_validate_claims_partitions(self) -> None:
        reg = build_evidence_registry(_payload())
        claims = [
            {"claim": "a", "evidence_id": "metric:xgboost:roc_auc", "quoted_value": 0.88},
            {"claim": "b", "evidence_id": "metric:xgboost:roc_auc", "quoted_value": 0.95},
            {"claim": "c", "evidence_id": None},
        ]
        out = validate_claims(claims, reg)
        assert [c["claim"] for c in out["supported"]] == ["a"]
        assert {c["claim"] for c in out["blocked"]} == {"b", "c"}
