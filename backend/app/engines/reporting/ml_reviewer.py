"""机器学习审查器（P2-03，updateplan §52；红线 8：数值全部来自 payload 真实计算）。

模拟 ML 评审视角，对一次分析运行做确定性规则审查，维度与 §52 对齐：

```text
Leakage / Overfitting / Validation / Calibration / Class imbalance / Feature importance
```

输出与 §51 统计审查同构的三段式（major_concerns / minor_concerns / questions），
每条附 basis 依据串（真实数值 + 阈值口径）。与 statistical_reviewer 的分工：
EPV/小样本/多重比较等统计学问题归 §51；本模块只覆盖 ML 工程视角。
完美指标红旗（T6.15）由 SR-PERFECT 统一呈现，本模块不重复报。

接入：报告第 9 章（局限性）末「ML 审查」块，紧随统计审查（docs/10 §2 增补条目）。
"""

from typing import Any

# 规则阈值（全部为本规则经验阈值，依据串明示）
_FOLD_CV_MAX = 0.10  # 折间变异系数（std/mean）上限
_IMBALANCE_LO, _IMBALANCE_HI = 0.1, 0.9  # 类别不均衡提示区间（同 limitations）
_IMBALANCE_EXTREME_LO, _IMBALANCE_EXTREME_HI = 0.05, 0.95  # 极端不均衡
_HL_ALPHA = 0.05  # Hosmer-Lemeshow 拒绝阈值
_CALIB_SLOPE_TOL = 0.3  # 校准斜率偏离 1 的容忍度
_DOMINANT_SECOND_MAX = 0.3  # 第二特征归一化重要性低于该值视为单特征主导


def _concern(cid: str, dimension: str, text: str, basis: str) -> dict[str, Any]:
    return {"id": cid, "dimension": dimension, "text": text, "basis": basis}


def _question(qid: str, text: str) -> dict[str, Any]:
    return {"id": qid, "text": text}


def review_ml(payload: dict[str, Any]) -> dict[str, Any]:
    """审查报告 payload，输出 Major/Minor/Questions 三段式结果（§52）。"""
    major: list[dict[str, Any]] = []
    minor: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []

    _review_leakage(payload, major, minor)
    _review_overfitting(payload, minor)
    _review_validation(payload, major)
    _review_calibration(payload, minor)
    _review_imbalance(payload, major, minor)
    _review_feature_importance(payload, minor, questions)

    return {
        "major_concerns": major,
        "minor_concerns": minor,
        "questions": questions,
        # LLM 表达增强槽位（规则保底；services 层按分功能开关补充，facts-only）
        "llm_summary": None,
    }


# ---------------------------------------------------------------------------
# 维度 1：Leakage
# ---------------------------------------------------------------------------


def _review_leakage(
    payload: dict[str, Any],
    major: list[dict[str, Any]],
    minor: list[dict[str, Any]],
) -> None:
    findings = (payload.get("integrity") or {}).get("findings") or []
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    warnings = [f for f in findings if f.get("severity") in ("warning", "critical")]
    if blockers:
        listed = "；".join(str(f.get("message")) for f in blockers[:3])
        major.append(
            _concern(
                "MLR-LEAKAGE-BLOCKER",
                "leakage",
                "泄漏完整性门禁发现阻断级问题：在排除前，所有性能指标不得解释为"
                "可信临床效能。请逐条核查下列发现（结局代理/时间泄漏/近 ID 列）。",
                f"integrity.findings（blocker，真实检出）：{listed}",
            )
        )
    if warnings:
        listed = "；".join(str(f.get("message")) for f in warnings[:3])
        minor.append(
            _concern(
                "MLR-LEAKAGE-WARN",
                "leakage",
                "泄漏检查存在警告级发现：相关特征与结局的关联路径需人工核实，"
                "确认其临床可得时间早于结局发生时间。",
                f"integrity.findings（warning/critical，真实检出）：{listed}",
            )
        )


# ---------------------------------------------------------------------------
# 维度 2：Overfitting
# ---------------------------------------------------------------------------


def _review_overfitting(payload: dict[str, Any], minor: list[dict[str, Any]]) -> None:
    """Top1 主指标折间变异系数 std/mean > 0.10 → 模型在本数据上不稳定。"""
    comparison = payload.get("comparison") or {}
    primary = (comparison.get("recommendation") or {}).get("primary_metric")
    ranking = comparison.get("ranking") or []
    if not primary or not ranking:
        return
    top_key = str(ranking[0])
    for row in payload.get("table") or []:
        if str(row.get("model_key")) != top_key:
            continue
        cell = (row.get("metrics") or {}).get(str(primary)) or {}
        mean, std = cell.get("mean"), cell.get("std")
        if mean is None or std is None or not mean:
            return
        cv = abs(float(std) / float(mean))
        if cv > _FOLD_CV_MAX:
            minor.append(
                _concern(
                    "MLR-FOLD-VAR",
                    "overfitting",
                    f"推荐模型 {top_key} 的主指标 {primary} 折间波动较大"
                    f"（mean={mean}，std={std}，变异系数 {cv:.2f}）：性能估计不稳定，"
                    "提示过拟合或数据异质性，建议重复交叉验证或简化模型。",
                    f"primary={primary}，mean={mean}，std={std}，"
                    f"CV=|{std}/{mean}|={round(cv, 4)}>{_FOLD_CV_MAX}（真实折级统计）",
                )
            )
        return


# ---------------------------------------------------------------------------
# 维度 3：Validation
# ---------------------------------------------------------------------------


def _review_validation(payload: dict[str, Any], major: list[dict[str, Any]]) -> None:
    if payload.get("validation") is None:
        major.append(
            _concern(
                "MLR-NO-VALIDATION",
                "validation",
                "本次运行缺少验证策略配置（strategy/n_splits/seed）：无法确认性能指标"
                "来自交叉验证而非训练集自评，结果不可复现也不可采信。",
                "payload.validation=None（preprocess_config.validation 缺失）",
            )
        )


# ---------------------------------------------------------------------------
# 维度 4：Calibration
# ---------------------------------------------------------------------------


def _review_calibration(payload: dict[str, Any], minor: list[dict[str, Any]]) -> None:
    if str((payload.get("run") or {}).get("task_type") or "") != "classification":
        return
    hl = (payload.get("calibration") or {}).get("hosmer_lemeshow") or {}
    hl_p = hl.get("p_value")
    if hl_p is not None and float(hl_p) < _HL_ALPHA:
        minor.append(
            _concern(
                "MLR-HL",
                "calibration",
                f"Hosmer-Lemeshow 校准检验 p={hl_p}，拒绝校准良好假设：预测概率与"
                "实际风险存在系统性偏差，用于风险分层前需做概率校准（如 Platt/"
                "isotonic）并在验证集复核。",
                f"HL p_value={hl_p}<{_HL_ALPHA}（推荐模型 OOF 概率真实检验）",
            )
        )
    comparison = payload.get("comparison") or {}
    ranking = comparison.get("ranking") or []
    if not ranking:
        return
    top_key = str(ranking[0])
    for row in payload.get("table") or []:
        if str(row.get("model_key")) != top_key:
            continue
        slope = ((row.get("metrics") or {}).get("calibration_slope") or {}).get("mean")
        if slope is None:
            return
        dev = abs(1.0 - float(slope))
        if dev > _CALIB_SLOPE_TOL:
            minor.append(
                _concern(
                    "MLR-CALIB-SLOPE",
                    "calibration",
                    f"推荐模型 {top_key} 的校准斜率为 {slope}（理想值 1.0）："
                    + ("预测概率整体过于极端（收缩不足）。" if float(slope) < 1 else "预测概率整体过于保守。")
                    + "建议做校准后处理再用于决策。",
                    f"calibration_slope mean={slope}，|1−slope|={round(dev, 4)}"
                    f">{_CALIB_SLOPE_TOL}（真实折级统计）",
                )
            )
        return


# ---------------------------------------------------------------------------
# 维度 5：Class imbalance
# ---------------------------------------------------------------------------


def _review_imbalance(
    payload: dict[str, Any],
    major: list[dict[str, Any]],
    minor: list[dict[str, Any]],
) -> None:
    prevalence = (payload.get("target_summary") or {}).get("prevalence")
    if prevalence is None:
        return
    p = float(prevalence)
    pct = f"{p * 100:.1f}%"
    if p < _IMBALANCE_EXTREME_LO or p > _IMBALANCE_EXTREME_HI:
        major.append(
            _concern(
                "MLR-IMBALANCE-EXTREME",
                "class_imbalance",
                f"结局类别极端不均衡（阳性率 {pct}）：常规训练流程几乎必然失效，"
                "必须采用类别权重/重采样并以 PR-AUC、灵敏度/特异度为核心指标；"
                "阈值需在验证集上独立校准。",
                f"prevalence={pct}，超出 [{_IMBALANCE_EXTREME_LO}, {_IMBALANCE_EXTREME_HI}]"
                "（target_summary 真实值）",
            )
        )
    elif p < _IMBALANCE_LO or p > _IMBALANCE_HI:
        minor.append(
            _concern(
                "MLR-IMBALANCE",
                "class_imbalance",
                f"结局类别不均衡（阳性率 {pct}）：默认 0.5 阈值的混淆矩阵解读需谨慎，"
                "建议使用类别权重、以 PR-AUC 为主要区分度指标并报告校准度。",
                f"prevalence={pct}，超出 [{_IMBALANCE_LO}, {_IMBALANCE_HI}]"
                "（target_summary 真实值）",
            )
        )


# ---------------------------------------------------------------------------
# 维度 6：Feature importance
# ---------------------------------------------------------------------------


def _review_feature_importance(
    payload: dict[str, Any],
    minor: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> None:
    comparison = payload.get("comparison") or {}
    if not comparison.get("ranking"):
        return
    charts = comparison.get("charts") or []
    fi = next((c for c in charts if c.get("kind") == "feature_importance"), None)
    hr = next((c for c in charts if c.get("kind") == "hr_forest"), None)
    if fi is None and hr is None:
        minor.append(
            _concern(
                "MLR-NO-EXPLAIN",
                "feature_importance",
                "本次分析无可解释性产物（特征重要性/HR 森林图均为空）：模型决策依据"
                "不可审查，投稿与临床采纳前需补充解释性分析。",
                "comparison.charts 中无 feature_importance / hr_forest（真实产物核对）",
            )
        )
        return
    if fi is None:
        return
    data = fi.get("data") or {}
    features = data.get("features") or []
    series = data.get("series") or []
    if len(features) < 2 or not series:
        return
    # 各模型归一化后第二特征均 <0.3 → 单特征主导（真实归一化值）
    seconds = [float(s.get("values", [None, None])[1]) for s in series if len(s.get("values") or []) > 1]
    if seconds and all(v < _DOMINANT_SECOND_MAX for v in seconds):
        top = str(features[0])
        minor.append(
            _concern(
                "MLR-DOMINANT-FEATURE",
                "feature_importance",
                f"特征「{top}」在所有模型中占据绝对主导（第二特征归一化重要性均 "
                f"<{_DOMINANT_SECOND_MAX}）：模型实质上依赖单一变量，需核实其"
                "是否为结局的代理变量或数据录入伪迹。",
                f"top 特征={top}；各模型第二特征归一化重要性={seconds}（feature_importance 图真实数据）",
            )
        )
        questions.append(
            _question(
                "MLQ-PROXY",
                f"主导特征「{top}」在临床上是否先于结局可得？它与结局之间是否存在"
                "记录/编码上的直接派生关系（如结局的定义本身包含该变量）？",
            )
        )
