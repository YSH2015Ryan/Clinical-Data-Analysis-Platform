"""AI Evidence Binding（updateplan §55，P2-07；红线 8：证据值全部来自真实计算）。

LLM/规则生成的每一条结论（claim）必须绑定结构化证据：

```text
build_evidence_registry(payload)   报告 payload → 可引用证据注册表（id → 真实值）
bind_claim(text, evidence_id, …)   claim ↔ 证据绑定（§55 契约形状）
validate_claims(claims, registry)  批量校验：证据不存在 / 引用值与真实值不符 → blocked
```

证据来源（全部真实计算，不编造）：
- metric:{model_key}:{metric}        模型指标（mean/std）
- figure:{chart_kind}                图表产物（无数值，引用数值即 block）
- fact:target_summary:{key}          样本事实（n_samples/prevalence/events/n_features）
- table:screening:{variable}         单因素筛选行（优先校正后 p，§30）
- metric:calibration:hosmer_lemeshow_p   校准检验 p 值

引用值容差 5%（与 engines/llm_validators 幻觉校验口径一致）；
§56：不在注册表内的证据 → Reject。
"""

from typing import Any

_REL_TOL = 0.05


def _is_close(a: float, b: float, rel_tol: float = _REL_TOL) -> bool:
    abs_tol = max(rel_tol * max(abs(a), abs(b)), 1e-9)
    return abs(a - b) <= abs_tol


def _entry(kind: str, value: float | None, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "value": value, **extra}


def build_evidence_registry(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """报告 payload → 证据注册表（{evidence_id: entry}）。空 payload → 空表不崩。"""
    payload = payload or {}
    registry: dict[str, dict[str, Any]] = {}

    for row in payload.get("table") or []:
        if not isinstance(row, dict):
            continue
        model_key = str(row.get("model_key"))
        for name, cell in (row.get("metrics") or {}).items():
            if not isinstance(cell, dict) or cell.get("mean") is None:
                continue
            registry[f"metric:{model_key}:{name}"] = _entry(
                "metric",
                float(cell["mean"]),
                model_key=model_key,
                metric=str(name),
                std=(float(cell["std"]) if cell.get("std") is not None else None),
            )

    for chart in ((payload.get("comparison") or {}).get("charts")) or []:
        if not isinstance(chart, dict) or not chart.get("kind"):
            continue
        eid = f"figure:{chart['kind']}"
        if eid not in registry:  # 同类多图去重，注册一次
            registry[eid] = _entry("figure", None, title=str(chart.get("title") or chart["kind"]))

    for key, val in (payload.get("target_summary") or {}).items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        registry[f"fact:target_summary:{key}"] = _entry("fact", float(val), field=str(key))

    for row in ((payload.get("screening") or {}).get("rows")) or []:
        if not isinstance(row, dict) or not row.get("variable"):
            continue
        p = row.get("p_adjusted") if row.get("p_adjusted") is not None else row.get("p_value")
        if p is None:
            continue
        registry[f"table:screening:{row['variable']}"] = _entry(
            "table",
            float(p),
            variable=str(row["variable"]),
            adjusted=row.get("p_adjusted") is not None,
        )

    hl = ((payload.get("calibration") or {}).get("hosmer_lemeshow")) or {}
    if hl.get("p_value") is not None:
        registry["metric:calibration:hosmer_lemeshow_p"] = _entry(
            "metric", float(hl["p_value"]), metric="hosmer_lemeshow_p"
        )

    return registry


def bind_claim(
    text: str,
    evidence_id: str | None,
    registry: dict[str, dict[str, Any]],
    quoted_value: float | None = None,
) -> dict[str, Any]:
    """绑定单条 claim 与证据（§55 契约：claim 携带结构化 evidence）。

    判定：
    - 证据 id 不在注册表 → supported=False, reason=evidence_not_found（§56 Reject）
    - 证据无数值而 claim 引用数值 → reason=no_numeric_value
    - 引用值与真实值偏差 >5% → reason=value_mismatch
    """
    entry = registry.get(evidence_id or "")
    if entry is None:
        return {
            "claim": text,
            "evidence": None,
            "supported": False,
            "reason": "evidence_not_found",
        }
    evidence = {"id": evidence_id, **entry}
    if quoted_value is not None:
        if entry["value"] is None:
            return {
                "claim": text,
                "evidence": evidence,
                "supported": False,
                "reason": "no_numeric_value",
            }
        if not _is_close(float(quoted_value), float(entry["value"])):
            return {
                "claim": text,
                "evidence": evidence,
                "supported": False,
                "reason": "value_mismatch",
            }
    return {"claim": text, "evidence": evidence, "supported": True, "reason": None}


def validate_claims(
    claims: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """批量校验 claim 清单，分为 supported / blocked（blocked 附 reason）。"""
    supported: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for c in claims:
        bound = bind_claim(
            str(c.get("claim") or ""),
            c.get("evidence_id"),
            registry,
            quoted_value=c.get("quoted_value"),
        )
        (supported if bound["supported"] else blocked).append(bound)
    return {"supported": supported, "blocked": blocked}
