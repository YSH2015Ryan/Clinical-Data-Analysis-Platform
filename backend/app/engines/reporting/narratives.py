"""报告三段式解读引擎（T6.15③；docs/10 §2 增补规范）。

四章（模型性能/比较推荐/特征重要性/临床意义）每个指标输出
「含义 / 判读规则 / 本数据数值结论」三段：含义与判读规则为统计教科书的
固定知识（不涉数据），本数据结论只引用 payload 真实计算值（红线 8）。
LLM 缺失时这些模板段落保证报告达到可读底线；LLM 在位时做上限增强。

判读规则的数值区间（AUC/C-index 0.7/0.8/0.9 分档等）为通用经验分档，
不构成医学断言；效应方向与因果判断一律不出现在本模块。
"""

from typing import Any

# 指标指南：含义（固定知识）+ 判读规则（通用分档）+ 方向（越高/越低越好）
_METRIC_GUIDE: dict[str, dict[str, Any]] = {
    "auc": {
        "title": "AUC（ROC 曲线下面积）",
        "meaning": "衡量模型区分阴性与阳性的能力：随机取一对正负样本，"
        "阳性样本得分更高的概率。0.5 相当于随机猜测，1.0 为完美区分。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "c_index": {
        "title": "C-index（一致性指数）",
        "meaning": "生存模型的区分度：所有可比较样本对中，预测风险顺序与"
        "实际结局顺序一致的比例。0.5 相当于随机，1.0 为完美排序。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "accuracy": {
        "title": "准确率（Accuracy）",
        "meaning": "全部样本中被正确分类的比例。类别不均衡时会高估模型表现，"
        "需结合敏感性/特异性解读。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "f1": {
        "title": "F1 分数",
        "meaning": "精确率与召回率的调和平均，类别不均衡时比准确率更稳健。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "sensitivity": {
        "title": "敏感性（召回率）",
        "meaning": "实际阳性样本中被正确检出的比例；筛查场景漏诊代价高时优先关注。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "specificity": {
        "title": "特异性",
        "meaning": "实际阴性样本中被正确排除的比例；误诊代价高时优先关注。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "precision": {
        "title": "精确率（阳性预测值）",
        "meaning": "预测为阳性的样本中真正阳性的比例，受患病率影响显著。",
        "rule": "通用分档：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。",
        "direction": "max",
        "bands": [(0.9, "优秀"), (0.8, "良好"), (0.7, "尚可"), (0.0, "欠佳")],
    },
    "brier": {
        "title": "Brier 分数",
        "meaning": "预测概率与实际结局的均方误差，同时反映区分度与校准度。",
        "rule": "越低越好；需与「全部预测为患病率」的基线值比较才有意义。",
        "direction": "min",
        "bands": [],
    },
    "ibs": {
        "title": "IBS（积分 Brier 分数）",
        "meaning": "Brier 分数在随访时间轴上的积分，综合评价生存预测的概率精度。",
        "rule": "越低越好；0.25 为无信息模型（恒预测 0.5）的理论上限参考。",
        "direction": "min",
        "bands": [],
    },
    "rmse": {
        "title": "RMSE（均方根误差）",
        "meaning": "预测值与真实值偏差的均方根，单位与结局变量一致，对大误差更敏感。",
        "rule": "越低越好；只有与结局变量的量纲/离散程度对比才能判断大小。",
        "direction": "min",
        "bands": [],
    },
    "mae": {
        "title": "MAE（平均绝对误差）",
        "meaning": "预测值与真实值偏差的平均绝对值，单位与结局变量一致，"
        "比 RMSE 更抗极端值。",
        "rule": "越低越好；只有与结局变量的量纲/离散程度对比才能判断大小。",
        "direction": "min",
        "bands": [],
    },
    "r2": {
        "title": "R²（决定系数）",
        "meaning": "模型解释结局变异的比例：1.0 为完美拟合，0 相当于直接用均值预测。",
        "rule": "通用分档：≥0.7 解释力较强，0.4–0.7 中等，<0.4 较弱。",
        "direction": "max",
        "bands": [(0.7, "解释力较强"), (0.4, "解释力中等"), (-1e9, "解释力较弱")],
    },
}

_STABILITY_TIGHT = 0.02  # std 低于该值：折间波动很小
_STABILITY_OK = 0.05  # std 低于该值：波动较小


def _verdict(bands: list[tuple[float, str]], value: float) -> str | None:
    for threshold, label in bands:
        if value >= threshold:
            return label
    return None


def _stability(std: float) -> str:
    if std < _STABILITY_TIGHT:
        return "折间波动很小，交叉验证估计较稳定"
    if std < _STABILITY_OK:
        return "折间波动较小"
    return "折间波动较大，单次划分的结果可能偏离该估计，解读需谨慎"


def build_performance_guides(
    table: list[dict[str, Any]] | None,
    top_model_key: str | None,
    primary_metric: str | None,
) -> list[dict[str, Any]]:
    """模型性能章三段式：覆盖表中出现的已知指标，主指标在前。

    本数据结论引用 Top1 模型（排名第一位）的真实 mean±std。
    """
    if not table:
        return []
    metric_names: list[str] = []
    for row in table:
        for name in (row.get("metrics") or {}):
            if name not in metric_names:
                metric_names.append(name)
    if primary_metric and primary_metric in metric_names:
        metric_names.remove(primary_metric)
        metric_names.insert(0, primary_metric)

    top_row = next(
        (r for r in table if r.get("model_key") == top_model_key),
        table[0] if table else None,
    )
    guides = []
    for name in metric_names:
        guide = _METRIC_GUIDE.get(name)
        if not guide:
            continue  # 未知指标不编造含义（红线 8）
        reading = None
        cell = ((top_row or {}).get("metrics") or {}).get(name)
        if cell and cell.get("mean") is not None:
            mean, std = float(cell["mean"]), float(cell.get("std") or 0.0)
            reading = (
                f"本数据排名首位的模型（{(top_row or {}).get('model_key')}）"
                f"{name}={mean:.4f}±{std:.4f}"
            )
            verdict = _verdict(guide["bands"], mean)
            if verdict:
                reading += f"，按上述分档属「{verdict}」区间"
            reading += f"；{_stability(std)}。"
        guides.append(
            {
                "metric": name,
                "title": guide["title"],
                "meaning": guide["meaning"],
                "rule": guide["rule"],
                "reading": reading,
            }
        )
    return guides


def build_comparison_guide(
    comparison: dict[str, Any] | None, table: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """比较推荐章三段式：排名含义/判读规则/本数据真实排名与配对检验。"""
    if not comparison:
        return None
    recommendation = comparison.get("recommendation") or {}
    ranking = comparison.get("ranking") or []
    top = recommendation.get("top") or []
    reading_parts = []
    if ranking:
        reading_parts.append("排名：" + " > ".join(str(k) for k in ranking))
    if top:
        reading_parts.append(f"Top1 {top[0]['model_key']}：{top[0]['reason']}")
    p_texts = [
        f"{r['model_key']} p={r['p_value_text']}"
        for r in (table or [])
        if r.get("p_value_text") and r["p_value_text"] not in ("参考", "—")
    ]
    if p_texts:
        reading_parts.append("与最佳模型的配对检验：" + "；".join(p_texts))
    return {
        "title": "模型排名与推荐",
        "meaning": "排名按披露公式加权（主指标 + 折间稳定性 + 次级指标），"
        "反映交叉验证平均表现而非单次划分结果。",
        "rule": "配对检验 p<0.05 提示与最佳模型的差异有统计学意义；"
        "差异不显著时，应优先选择更简单/更可解释的模型。",
        "reading": "；".join(reading_parts) if reading_parts else None,
    }


def build_explainability_guides(charts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """特征重要性章三段式：含义/判读规则/本数据 Top 特征（真实特征名）。"""
    guides = []
    for chart in charts or []:
        kind = chart.get("kind")
        features = (chart.get("data") or {}).get("features") or []
        if kind == "feature_importance":
            reading = (
                "贡献最大的特征依次为：" + "、".join(str(f) for f in features[:5]) + "。"
                if features
                else None
            )
            guides.append(
                {
                    "title": "特征重要性",
                    "meaning": "衡量各特征对模型预测的贡献大小（排列重要性/增益等，"
                    "取决于模型实现）。",
                    "rule": "排序越前贡献越大；重要性反映相关性而非因果，"
                    "高重要性特征需结合临床先验核查其合理性。",
                    "reading": reading,
                }
            )
        elif kind == "hr_forest":
            reading = (
                "纳入分析的特征：" + "、".join(str(f) for f in features[:5]) + "。"
                if features
                else None
            )
            guides.append(
                {
                    "title": "风险比（HR）森林图",
                    "meaning": "HR>1 表示该特征取值升高与风险升高相关，HR<1 相反；"
                    "横线为该特征 HR 的 95% 置信区间。",
                    "rule": "置信区间跨过 1 时该关联无统计学意义；"
                    "HR 是多变量校正后的关联强度，仍不等于因果效应。",
                    "reading": reading,
                }
            )
    return guides


def build_clinical_guides(
    diagnostics: dict[str, Any] | None,
    calibration: dict[str, Any] | None,
    survival_analysis: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """临床意义章三段式：为实际存在的分析产物（校准/诊断/分层）配含义与规则，
    本数据结论引用引擎产出的真实结论文本。"""
    guides = []
    if calibration:
        readings = []
        hl = calibration.get("hosmer_lemeshow") or {}
        if hl.get("conclusion"):
            readings.append(str(hl["conclusion"]))
        threshold = calibration.get("optimal_threshold") or {}
        if threshold.get("interpretation"):
            readings.append(str(threshold["interpretation"]))
        guides.append(
            {
                "title": "校准度",
                "meaning": "预测概率与实际发生频率的一致性：区分度（AUC）高的模型"
                "也可能系统性高估或低估风险。",
                "rule": "Hosmer-Lemeshow 检验 p>0.05 提示校准偏差无统计学意义；"
                "临床落地前还应看校准曲线与决策曲线（DCA）的净获益区间。",
                "reading": "；".join(readings) if readings else None,
            }
        )
    if diagnostics:
        readings = [
            str(diagnostics[k]["conclusion"])
            for k in ("shapiro", "breusch_pagan", "durbin_watson")
            if (diagnostics.get(k) or {}).get("conclusion")
        ]
        guides.append(
            {
                "title": "回归诊断",
                "meaning": "检验回归模型的统计假设（残差正态性/同方差性/自相关），"
                "假设不满足时 p 值与置信区间的推断可能失真。",
                "rule": "假设检验 p>0.05 表示未发现违背假设的证据；"
                "样本量较大时轻微偏离也会显著，需结合残差图判断实际影响。",
                "reading": "；".join(readings) if readings else None,
            }
        )
    logrank = (survival_analysis or {}).get("logrank") or {}
    if logrank.get("statistic") is not None:
        p = logrank.get("p_value")
        p_text = f"{p:.3g}" if isinstance(p, (int, float)) and p == p else "—"
        guides.append(
            {
                "title": "高低风险分层 log-rank 检验",
                "meaning": "按模型预测风险中位数分组后，比较两组生存曲线差异，"
                "直观验证模型的风险分层能力。",
                "rule": "p<0.05 提示两组生存曲线差异有统计学意义；"
                "该检验基于模型自身的分组，证据强度低于独立外部验证。",
                "reading": f"χ²={logrank['statistic']:.4f}，p={p_text}；"
                f"高风险组 {logrank.get('n_high')} 例、低风险组 {logrank.get('n_low')} 例。",
            }
        )
    return guides
