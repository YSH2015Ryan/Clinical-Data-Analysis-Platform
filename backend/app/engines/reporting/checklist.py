"""报告规范自查（T6.11）：TRIPOD 核心条目 + STROBE 通用条目核对。

每条目的状态与依据均由 payload 真实字段推导（样本量/事件数/EPV/验证策略/
预处理步骤/校准结果等），不凭空判定（红线8）；结论仅供投稿前参考。
"""

from typing import Any

_STATUS_MET = "满足"
_STATUS_PARTIAL = "部分满足"
_STATUS_PENDING = "待补充"
_STATUS_NA = "不适用"

_EPV_THRESHOLD = 10


def _item(no: int, item: str, status: str, evidence: str) -> dict[str, Any]:
    return {"no": no, "item": item, "status": status, "evidence": evidence}


def _sample_size_item(payload: dict[str, Any]) -> tuple[str, str]:
    summary = payload.get("target_summary") or {}
    n = summary.get("n_samples")
    if n is None:
        return _STATUS_PENDING, "样本量未在分析产物中记录"
    return _STATUS_MET, f"纳入样本 {n} 例（分析运行真实计数）"


def _outcome_item(payload: dict[str, Any], task_type: str) -> tuple[str, str]:
    summary = payload.get("target_summary") or {}
    if task_type == "classification":
        positives, prevalence = summary.get("positives"), summary.get("prevalence")
        if positives is not None and prevalence is not None:
            return (
                _STATUS_MET,
                f"阳性 {positives} 例，阳性率 {prevalence:.2%}（结局列真实计数）",
            )
        counts = summary.get("class_counts")
        if counts:
            return _STATUS_MET, f"各类别样本数：{counts}"
        return _STATUS_PENDING, "结局类别分布未记录"
    if task_type == "survival":
        events, followup = summary.get("events"), summary.get("median_followup")
        if events is not None:
            text = f"事件数 {events}"
            if followup is not None:
                text += f"，中位随访 {followup}"
            return _STATUS_MET, text
        return _STATUS_PENDING, "事件数未记录"
    mean = summary.get("label_mean")
    if mean is not None:
        return _STATUS_MET, f"结局均值 {mean}（连续结局）"
    return _STATUS_PENDING, "结局分布未记录"


def _epv_item(payload: dict[str, Any], task_type: str) -> tuple[str, str]:
    if task_type == "regression":
        return _STATUS_NA, "EPV 适用于分类/生存结局，回归任务核对 n/p（见样本量条目）"
    summary = payload.get("target_summary") or {}
    k = summary.get("n_features")
    events = summary.get("events") if task_type == "survival" else summary.get("positives")
    if events is None or not k:
        return _STATUS_PENDING, "事件/阳性数或预测因子数未记录，无法核对 EPV"
    epv = events / k
    status = _STATUS_MET if epv >= _EPV_THRESHOLD else _STATUS_PARTIAL
    return (
        status,
        f"事件/阳性数 {events}，预测因子 {k} 个，EPV = {epv:.1f}（经验下限 {_EPV_THRESHOLD}）",
    )


def _validation_item(payload: dict[str, Any]) -> tuple[str, str]:
    validation = payload.get("validation") or {}
    strategy = validation.get("strategy")
    if not strategy:
        return _STATUS_PENDING, "未记录内部验证策略"
    return (
        _STATUS_MET,
        f"内部验证：{strategy}（n_splits={validation.get('n_splits')}，"
        f"seed={validation.get('seed')}）",
    )


def _models_item(payload: dict[str, Any]) -> tuple[str, str]:
    models = (payload.get("run") or {}).get("selected_models") or []
    if not models:
        return _STATUS_PENDING, "未记录候选模型列表"
    comparison = payload.get("comparison") or {}
    top = ((comparison.get("recommendation") or {}).get("top") or [None])[0]
    text = f"候选模型 {len(models)} 个：{'、'.join(models)}"
    if top:
        text += f"；推荐 {top['model_key']}（{top['reason']}）"
    return _STATUS_MET, text


def _discrimination_item(payload: dict[str, Any], task_type: str) -> tuple[str, str]:
    metric_names: set[str] = set()
    for row in payload.get("table") or []:
        for name in row.get("metrics") or {}:
            metric_names.add(name)
    expect = {
        "classification": "AUC",
        "survival": "C-index",
        "regression": "RMSE/R²",
    }[task_type]
    if metric_names:
        reported = "、".join(sorted(metric_names))
        return _STATUS_MET, f"区分度/误差指标已报告（{expect} 等）：{reported}"
    return _STATUS_PENDING, f"未报告区分度/误差指标（{expect}）"


def _uncertainty_item(payload: dict[str, Any]) -> tuple[str, str]:
    for row in payload.get("table") or []:
        for val in (row.get("metrics") or {}).values():
            if isinstance(val, dict) and val.get("std") is not None:
                return _STATUS_MET, "性能指标含折间标准差（交叉验证折级真实分布）"
    return _STATUS_PENDING, "性能指标未含不确定性度量（标准差/置信区间）"


def _calibration_item(payload: dict[str, Any], task_type: str) -> tuple[str, str]:
    calibration = payload.get("calibration")
    if calibration:
        hl = calibration.get("hosmer_lemeshow") or {}
        p = hl.get("p")
        text = "校准评估已完成（Hosmer-Lemeshow"
        text += f" p={p:.3f}）" if isinstance(p, int | float) else "）"
        return _STATUS_MET, text
    if task_type == "classification":
        return _STATUS_PENDING, "分类预测模型应报告校准度（校准曲线/Hosmer-Lemeshow）"
    return _STATUS_NA, "校准度评估主要针对分类预测模型"


def _missing_item(payload: dict[str, Any]) -> tuple[str, str]:
    steps = payload.get("preprocess_steps") or []
    imputes = [s for s in steps if "impute" in str(s.get("type", ""))]
    if imputes:
        return _STATUS_MET, f"缺失值处理：{imputes[0].get('type')}（{imputes[0].get('params')}）"
    return _STATUS_PENDING, "未记录缺失值处理步骤"


def _reproducibility_item(payload: dict[str, Any]) -> tuple[str, str]:
    seed = (payload.get("validation") or {}).get("seed")
    software = payload.get("software") or {}
    if seed is not None and software:
        return _STATUS_MET, f"随机种子 seed={seed}；软件版本已记录（{len(software)} 项）"
    return _STATUS_PENDING, "随机种子或软件版本未完整记录"


def build_reporting_checklist(payload: dict[str, Any]) -> dict[str, Any]:
    """TRIPOD/STROBE 自查：逐条目状态 + 真实依据。

    Args:
        payload: report worker 装配的完整 payload（build_report_context 输入）。
    """
    task_type = str((payload.get("run") or {}).get("task_type") or "classification")
    if task_type not in {"classification", "survival", "regression"}:
        task_type = "classification"

    builders = [
        ("样本量报告", _sample_size_item(payload)),
        ("结局事件数/分布报告", _outcome_item(payload, task_type)),
        ("每变量事件数（EPV）核对", _epv_item(payload, task_type)),
        ("内部验证方法", _validation_item(payload)),
        ("候选模型与选择依据", _models_item(payload)),
        ("区分度/误差指标", _discrimination_item(payload, task_type)),
        ("性能不确定性度量", _uncertainty_item(payload)),
        ("校准度评估", _calibration_item(payload, task_type)),
        ("缺失值处理", _missing_item(payload)),
        ("可复现性（随机种子/软件版本）", _reproducibility_item(payload)),
    ]
    items = [
        _item(i + 1, name, status, evidence)
        for i, (name, (status, evidence)) in enumerate(builders)
    ]
    met = sum(1 for i in items if i["status"] == _STATUS_MET)
    return {
        "standard": "TRIPOD（预测模型报告规范）+ STROBE 通用条目",
        "items": items,
        "met": met,
        "total": len(items),
        "note": "自查结果由系统按本次分析真实产物核对，仅供投稿前参考，最终以目标期刊要求为准。",
    }
