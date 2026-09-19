"""统计方法学自动审查（P2-02，updateplan §51；红线 8：数值全部来自 payload 真实计算）。

模拟期刊统计审稿人视角，对一次分析运行的方法学做确定性规则审查，
审查维度与 §51 对齐：

```text
Sample size / Missing data / Duplicate data / Variable selection /
Statistical method / Multiple comparisons / Validation strategy
```

输出三段式（§51）：

```text
major_concerns  Major Concerns（须在投稿前解决的方法学问题）
minor_concerns  Minor Concerns（建议在报告中声明的局限）
questions       Questions for Researchers（需研究者回答的问题）
```

每个 concern 附 basis 依据串（真实数值 + 阈值口径，可展开核对）；
规则全部为确定性判断、可复现。LLM 表达增强预留 llm_summary 槽位
（本模块不调用 LLM；接线时由 services 层按分功能开关补充，facts-only）。

接入：报告第 9 章（局限性）末尾「统计审查」块（docs/10 §2 增补条目）。
"""

from typing import Any

from app.engines.reporting.redflags import detect_perfect_metric_redflag

# 规则阈值（口径与 reporting/limitations.py 同源，注释注明出处）
_EPV_MIN = 10.0  # Peduzzi 1996 每变量事件数经验阈值
_SMALL_SAMPLE = 200  # 小样本提示阈值（同 limitations）
_MISSING_RATE_HIGH = 0.2  # 高缺失列阈值（同 docs/05 missing_warn）
_MISSING_RATE_ANY = 0.05  # 触发「缺失机制评估」问题的下限
_REG_NP_MIN = 10.0  # 回归任务每变量样本数经验下限
_CV_FOLDS_MIN = 5  # 交叉验证折数下限
_PAIRWISE_P_MIN_MODELS = 3  # 性能表两两 t 检验未校正的触发模型数

_KFOLD_STRATEGIES = {"kfold", "stratified_kfold"}


def _concern(cid: str, dimension: str, text: str, basis: str) -> dict[str, Any]:
    return {"id": cid, "dimension": dimension, "text": text, "basis": basis}


def _question(qid: str, text: str) -> dict[str, Any]:
    return {"id": qid, "text": text}


def review_methodology(payload: dict[str, Any]) -> dict[str, Any]:
    """审查报告 payload，输出 Major/Minor/Questions 三段式结果。"""
    run = payload.get("run") or {}
    task_type = str(run.get("task_type") or "")
    summary = payload.get("target_summary") or {}
    n_samples = summary.get("n_samples")
    n_features = summary.get("n_features")
    quality = payload.get("quality_report") or {}
    issues = quality.get("issues") or []
    profiles = quality.get("column_profiles") or []
    missingness = payload.get("missingness")
    screening = payload.get("screening")
    validation = payload.get("validation") or {}
    table = payload.get("table") or []

    major: list[dict[str, Any]] = []
    minor: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []

    _review_sample_size(task_type, summary, n_samples, n_features, major, minor)
    _review_missing(profiles, missingness, minor, questions)
    _review_duplicates(issues, major)
    _review_variable_selection(n_samples, n_features, screening, minor, questions)
    _review_method(payload, run, task_type, minor, questions)
    _review_multiple_comparisons(screening, table, major, minor)
    _review_validation(payload, validation, profiles, major, minor, questions)

    # §51 固定问题：外部验证（任何回顾性单队列分析都应回答）
    questions.append(
        _question(
            "SRQ-EXTERNAL",
            "模型仅在本数据集内部交叉验证，未做外部验证；是否有独立队列或"
            "时间外/空间外验证计划？无外部队列时结论的外推性需在论文中明确声明。",
        )
    )

    return {
        "major_concerns": major,
        "minor_concerns": minor,
        "questions": questions,
        # LLM 表达增强槽位（规则保底；services 层按分功能开关补充，facts-only）
        "llm_summary": None,
    }


# ---------------------------------------------------------------------------
# 维度 1：Sample size
# ---------------------------------------------------------------------------


def _review_sample_size(
    task_type: str,
    summary: dict[str, Any],
    n_samples: Any,
    n_features: Any,
    major: list[dict[str, Any]],
    minor: list[dict[str, Any]],
) -> None:
    if task_type in ("classification", "survival") and n_features:
        events = (
            summary.get("positives") if task_type == "classification" else summary.get("events")
        )
        if events is not None:
            epv = events / n_features
            if epv < _EPV_MIN:
                event_label = "阳性事件数" if task_type == "classification" else "生存事件数"
                major.append(
                    _concern(
                        "SR-EPV",
                        "sample_size",
                        f"每变量事件数（EPV）仅 {epv:.1f}，低于经验阈值 {int(_EPV_MIN)}："
                        "回归系数与模型性能估计不稳定，过拟合风险高；建议减少入模变量、"
                        "采用正则化模型或补充样本。",
                        f"EPV={event_label}/特征数={events}/{n_features}={round(epv, 4)}"
                        f"<{int(_EPV_MIN)}（Peduzzi 1996）",
                    )
                )
    if task_type == "regression" and n_samples is not None and n_features:
        np_ratio = n_samples / n_features
        if np_ratio < _REG_NP_MIN:
            minor.append(
                _concern(
                    "SR-REG-NP",
                    "sample_size",
                    f"回归任务每变量样本数仅 {np_ratio:.1f}（n={n_samples}，p={n_features}），"
                    "低于经验下限 10，系数估计方差较大。",
                    f"每变量样本数={n_samples}/{n_features}={round(np_ratio, 4)}<{int(_REG_NP_MIN)}"
                    "（本规则经验阈值）",
                )
            )
    if n_samples is not None and n_samples < _SMALL_SAMPLE:
        minor.append(
            _concern(
                "SR-SMALL-N",
                "sample_size",
                f"样本量较小（N={n_samples}）：交叉验证估计的折间波动可能掩盖真实的模型间差异，"
                "结论应附带不确定性声明。",
                f"n_samples={n_samples}<{_SMALL_SAMPLE}（本规则经验阈值）",
            )
        )


# ---------------------------------------------------------------------------
# 维度 2：Missing data
# ---------------------------------------------------------------------------


def _review_missing(
    profiles: list[dict[str, Any]],
    missingness: dict[str, Any] | None,
    minor: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> None:
    high = [
        (str(p.get("name")), float(p.get("missing_rate") or 0.0))
        for p in profiles
        if float(p.get("missing_rate") or 0.0) > _MISSING_RATE_HIGH
    ]
    if high:
        listed = "、".join(f"{n}（{r * 100:.1f}%）" for n, r in high[:3])
        minor.append(
            _concern(
                "SR-MISS-HIGH",
                "missing_data",
                f"变量 {listed} 缺失率超过 {int(_MISSING_RATE_HIGH * 100)}%："
                "分析结果对缺失处理方式的敏感性较高，建议做缺失机制与敏感性分析。",
                f"缺失率>{_MISSING_RATE_HIGH} 的列：{listed}（真实缺失率，最多列 3 个）",
            )
        )
    if (missingness or {}).get("has_outcome_associated_missingness"):
        minor.append(
            _concern(
                "SR-MNAR",
                "missing_data",
                "存在与结局相关的缺失模式（疑似 MNAR）：完全病例或单一插补可能引入偏倚，"
                "建议报告缺失模式并进行多重插补敏感性分析。",
                "missingness.has_outcome_associated_missingness=True"
                "（缺失指示变量与结局关联检验，P1-11 启发式）",
            )
        )
    any_missing = any(float(p.get("missing_rate") or 0.0) > _MISSING_RATE_ANY for p in profiles)
    if any_missing and missingness is None:
        questions.append(
            _question(
                "SRQ-MISSING-MECH",
                "数据存在缺失但未附缺失机制（MCAR/MAR/MNAR）评估；缺失机制是什么？"
                "采用的缺失处理方式在该机制假设下是否合理？",
            )
        )


# ---------------------------------------------------------------------------
# 维度 3：Duplicate data
# ---------------------------------------------------------------------------


def _review_duplicates(issues: list[dict[str, Any]], major: list[dict[str, Any]]) -> None:
    dup_issues = [i for i in issues if i.get("rule_id") == "RV401"]
    if not dup_issues:
        return
    total = sum(int(i.get("affected_rows") or 0) for i in dup_issues)
    messages = "；".join(str(i.get("message")) for i in dup_issues[:2])
    major.append(
        _concern(
            "SR-DUP",
            "duplicate_data",
            "数据含重复记录：同一观测若同时进入训练与验证折将高估模型性能；"
            "请确认已按患者级别去重，且数据切分以患者（而非记录）为单位。",
            f"质量报告 RV401：{messages}（合计 affected_rows={total}，真实计数）",
        )
    )


# ---------------------------------------------------------------------------
# 维度 4：Variable selection
# ---------------------------------------------------------------------------


def _review_variable_selection(
    n_samples: Any,
    n_features: Any,
    screening: dict[str, Any] | None,
    minor: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> None:
    if n_samples and n_features and n_features > n_samples / 10:
        minor.append(
            _concern(
                "SR-WIDE",
                "variable_selection",
                f"入模特征数（{n_features}）相对样本量（{n_samples}）偏多："
                "特征/样本比超过 1:10，建议先做降维或基于临床先验筛选变量。",
                f"特征/样本比={n_features}/{n_samples}=1:{round(n_samples / n_features, 1)}"
                "（本规则经验阈值 1:10）",
            )
        )
    if screening is not None:
        n_tests = screening.get("n_tests") or screening.get("n_total_tested")
        questions.append(
            _question(
                "SRQ-SCREENING",
                f"单因素筛选（{n_tests or '多'} 项检验）与建模在同一数据集上进行："
                "基于结局的筛选结果直接入模存在选择偏倚；是否在交叉验证各训练折内"
                "重新做筛选，或报告筛选前后的敏感性对比？",
            )
        )


# ---------------------------------------------------------------------------
# 维度 5：Statistical method
# ---------------------------------------------------------------------------


def _review_method(
    payload: dict[str, Any],
    run: dict[str, Any],
    task_type: str,
    minor: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> None:
    models = run.get("selected_models") or []
    if len(models) == 1:
        minor.append(
            _concern(
                "SR-SINGLE-MODEL",
                "statistical_method",
                f"仅评估了 1 个模型（{models[0]}）：无模型间比较，无法判断所选模型"
                "是否适配本数据，建议至少加入一个结构不同的对照模型。",
                f"selected_models={models}（len=1）",
            )
        )
    if task_type == "regression" and payload.get("diagnostics") is None:
        questions.append(
            _question(
                "SRQ-DIAG",
                "本次回归分析未附残差诊断（正态性/同方差性/自相关/共线性）；"
                "模型假设是否满足？请补充诊断或说明不使用回归假定的理由。",
            )
        )
    if task_type == "classification" and payload.get("calibration") is None:
        questions.append(
            _question(
                "SRQ-CALIB",
                "本次分类分析未附校准度评估（如 Hosmer-Lemeshow / 校准曲线）；"
                "预测概率是否经校准？未校准的概率不宜直接用于临床风险分层。",
            )
        )


# ---------------------------------------------------------------------------
# 维度 6：Multiple comparisons
# ---------------------------------------------------------------------------


def _review_multiple_comparisons(
    screening: dict[str, Any] | None,
    table: list[dict[str, Any]],
    major: list[dict[str, Any]],
    minor: list[dict[str, Any]],
) -> None:
    if screening is not None and screening.get("correction") == "none":
        n_tests = screening.get("n_tests") or screening.get("n_total_tested")
        major.append(
            _concern(
                "SR-MC-NONE",
                "multiple_comparisons",
                f"单因素筛选进行了 {n_tests or '多'} 项检验但未做多重比较校正："
                "假阳性率随检验数线性膨胀，入选特征不可直接作为「显著关联」报告；"
                "请改用 BH(FDR) 或 Bonferroni 校正后重新筛选。",
                f"screening.correction=none，n_tests={n_tests}（真实检验计数）",
            )
        )
    p_rows = [r for r in table if r.get("p_value_text")]
    if len(table) >= _PAIRWISE_P_MIN_MODELS and p_rows:
        minor.append(
            _concern(
                "SR-MC-PAIRWISE",
                "multiple_comparisons",
                f"性能表含 {len(p_rows)} 组与最佳模型的两两配对 t 检验（未做多重比较校正）："
                "p 值仅供模型间差异的线索参考，不宜作为确定性结论。",
                f"table 行数={len(table)}，含 p 值行数={len(p_rows)}"
                "（T6.4 折级配对 t 检验，未校正）",
            )
        )


# ---------------------------------------------------------------------------
# 维度 7：Validation strategy
# ---------------------------------------------------------------------------


def _review_validation(
    payload: dict[str, Any],
    validation: dict[str, Any],
    profiles: list[dict[str, Any]],
    major: list[dict[str, Any]],
    minor: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> None:
    n_splits = validation.get("n_splits")
    if n_splits is not None and int(n_splits) < _CV_FOLDS_MIN:
        minor.append(
            _concern(
                "SR-CV-FOLDS",
                "validation_strategy",
                f"交叉验证折数仅 {n_splits}：每折验证集偏大、折间方差高，"
                f"建议 ≥{_CV_FOLDS_MIN} 折或重复交叉验证以获得更稳定的估计。",
                f"validation.n_splits={n_splits}<{_CV_FOLDS_MIN}（真实配置）",
            )
        )
    has_datetime = any(p.get("inferred_type") == "datetime" for p in profiles)
    if has_datetime and str(validation.get("strategy") or "") in _KFOLD_STRATEGIES:
        questions.append(
            _question(
                "SRQ-TEMPORAL",
                "数据含日期/时间列而验证采用随机 K 折：若样本存在时间顺序，随机切分"
                "会让未来信息泄漏进训练折；是否应改用时间序列交叉验证（按时间先后切分）？",
            )
        )
    # T6.15 红旗复用（完整性门禁触发时不重复——状态灯已强制 RED）
    red_flag = detect_perfect_metric_redflag(payload)
    if red_flag and not red_flag.get("integrity_blocked"):
        major.append(
            _concern(
                "SR-PERFECT",
                "validation_strategy",
                "主指标接近满分而 EPV 不足：性能很可能由过拟合或数据泄漏驱动，"
                "排除泄漏前所有性能解读不可信（详见局限性章红旗条目）。",
                str(red_flag.get("limitation") or ""),
            )
        )
