"""报告生成任务（docs/10 §3 渲染管线；docs/12 §3 generate_report 入 report 队列）。

generate_report(report_id)：DB 装配 payload → build_report_context →
图表 JSON 渲染 PNG（单数据源，base64 注入模板）→ render_html → 存储落
reports/{id}/report.{format} → Report READY；异常 → FAILED（不抛出，幂等重入）。
"""

import importlib.metadata
import io
import platform
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import select

from app.core.logging import get_logger
from app.engines.comparison.statistics import (
    add_pvalues_to_performance_table,
    add_statistical_significance_note,
)
from app.engines.reporting.baseline_table import generate_baseline_table
from app.engines.reporting.chart_png import chart_to_b64
from app.engines.reporting.context import build_report_context
from app.engines.reporting.diagnostics import (
    breusch_pagan_test,
    durbin_watson_test,
    generate_diagnostic_paragraph,
    ols_coefficient_table,
    shapiro_wilk_test,
    vif_analysis,
)
from app.engines.reporting.docx_export import context_to_docx
from app.engines.reporting.effect_size import compute_optimal_threshold, hosmer_lemeshow_test
from app.engines.reporting.markdown_export import html_to_markdown
from app.engines.reporting.pdf import html_to_pdf
from app.engines.reporting.render import TEMPLATE_KEY, TEMPLATE_VERSION, render_html
from app.engines.reporting.survival_extra import at_risk_table, median_risk_logrank
from app.engines.screening import univariate_screen
from app.models.entities import (
    AnalysisRun,
    Comparison,
    Dataset,
    DatasetInsight,
    DatasetVersion,
    ModelResult,
    PreprocessSnapshot,
    QualityReport,
    Report,
)
from app.services import llm_tasks
from app.services.llm import init_llm_service_from_runtime
from app.services.settings import get_llm_config_sync
from app.services.storage import key_from_uri, storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)

_SOFTWARE_PACKAGES = [
    "scikit-learn",
    "lifelines",
    "scikit-survival",
    "numpy",
    "pandas",
    "matplotlib",
    "jinja2",
    "weasyprint",
    "python-docx",
]

# 报告产物 Content-Type（docs/10 §4）：预览 iframe 依赖浏览器按 MIME 渲染
_CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "markdown": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _software_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for pkg in _SOFTWARE_PACKAGES:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


def _read_parquet(storage: Any, key: str) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(io.BytesIO(storage.get(key)))
    except Exception:
        return None


def _target_summary(storage: Any, run_id: uuid.UUID, task_type: str) -> dict[str, Any] | None:
    """target/features parquet → 数据概况统计（真实计算；缺文件 → None → 不适用）。"""
    target = _read_parquet(storage, f"runs/{run_id}/target.parquet")
    features = _read_parquet(storage, f"runs/{run_id}/features.parquet")
    if target is None:
        return None
    summary: dict[str, Any] = {
        "n_samples": len(target),
        "n_features": int(features.shape[1]) if features is not None else None,
    }
    if task_type == "classification":
        label_col = target["label"]
        n_classes = int(label_col.nunique())
        summary["n_classes"] = n_classes
        if n_classes == 2:
            # 二分类：计算阳性率（假设较大值为阳性，与训练 label encoding 一致）
            positives = int((label_col == label_col.max()).sum())
            summary["positives"] = positives
            summary["prevalence"] = round(positives / len(target), 6) if len(target) else 0.0
        else:
            # 多分类：记录各类别样本数
            summary["class_counts"] = label_col.value_counts().to_dict()
    elif task_type == "survival":
        summary["events"] = int(target["event"].sum())
        summary["median_followup"] = round(float(target["time"].median()), 4)
    else:
        summary["label_mean"] = round(float(target["label"].mean()), 4)
    return summary


def _enhanced_table(
    results: list[ModelResult], comparison: Comparison | None, task_type: str
) -> list[dict[str, Any]]:
    """性能表（T6.4）：按 ranking 排序 + 与最佳模型配对检验 p 值列。

    失败/无指标行排在末尾，不参与 p 值计算；数据源为 ModelResult.metrics
    的折级数据（与训练落库同源，不重新计算指标）。
    """
    table = [
        {
            "model_key": r.model_key,
            "status": r.status,
            "metrics": r.metrics,
            "duration_ms": r.duration_ms,
        }
        for r in results
    ]
    if comparison is None:
        return table
    ranking = [str(k) for k in (comparison.ranking or [])]
    order = {key: i for i, key in enumerate(ranking)}
    table.sort(key=lambda r: order.get(str(r["model_key"]), len(order)))
    n_success = sum(1 for r in table if r["status"] == "SUCCESS" and r["metrics"])
    succeeded = table[:n_success]
    enhanced = add_pvalues_to_performance_table(succeeded, task_type, {"rows": succeeded})
    return [*enhanced, *table[n_success:]]


def _baseline_table_payload(storage: Any, run: AnalysisRun) -> dict[str, Any] | None:
    """基线特征表（T6.3，Table 1）：原始特征 + 目标分层（分类按 label、生存按 event）。

    真实列级统计 + 组间差异检验；任何异常 → None（报告降级为不适用，不阻断）。
    """
    raw = _read_parquet(storage, f"runs/{run.id}/raw_features.parquet")
    target = _read_parquet(storage, f"runs/{run.id}/target.parquet")
    if raw is None or target is None:
        return None
    df = raw.copy()
    stratify_by: str | None = None
    target_cfg = (run.preprocess_config or {}).get("target") or {}
    if run.task_type == "classification":
        label_col = str(target_cfg.get("label_col") or "label")
        if target["label"].nunique() <= 5:
            df[label_col] = target["label"].to_numpy()
            stratify_by = label_col
    elif run.task_type == "survival":
        event_col = str(target_cfg.get("event_col") or "event")
        df[event_col] = target["event"].to_numpy()
        stratify_by = event_col
    try:
        table = generate_baseline_table(
            df, stratify_by=stratify_by, test_difference=stratify_by is not None
        )
    except Exception as exc:
        logger.error("baseline_table_failed", run_id=str(run.id), error=str(exc))
        return None
    return table if table["rows"] else None


def _regression_diagnostics(
    storage: Any, run_id: uuid.UUID, ranking: list[str]
) -> dict[str, Any] | None:
    """回归诊断（T6.3）：推荐模型 OOF 残差 → 正态/同方差/自相关/VIF + OLS 系数表。"""
    if not ranking:
        return None
    top_key = ranking[0]
    oof = _read_parquet(storage, f"runs/{run_id}/oof_{top_key}.parquet")
    target = _read_parquet(storage, f"runs/{run_id}/target.parquet")
    if oof is None or target is None or "oof" not in oof.columns:
        return None
    y = pd.to_numeric(target["label"], errors="coerce").to_numpy(dtype=float)
    pred = oof["oof"].to_numpy(dtype=float)
    if len(y) != len(pred):
        return None
    residuals = y - pred
    features = _read_parquet(storage, f"runs/{run_id}/features.parquet")
    feature_names = [str(c) for c in features.columns] if features is not None else None
    X = features.to_numpy(dtype=float) if features is not None else None
    shapiro = shapiro_wilk_test(residuals)
    bp = breusch_pagan_test(X, residuals) if X is not None else None
    return {
        "model_key": top_key,
        "shapiro": shapiro,
        "breusch_pagan": bp,
        "durbin_watson": durbin_watson_test(residuals),
        "vif": vif_analysis(X, feature_names) if X is not None and X.shape[1] >= 2 else None,
        "coefficients": ols_coefficient_table(X, y, feature_names) if X is not None else None,
        "paragraph": generate_diagnostic_paragraph(shapiro, bp),
    }


def _classification_calibration(
    storage: Any, run_id: uuid.UUID, ranking: list[str]
) -> dict[str, Any] | None:
    """分类校准（T6.3）：推荐模型 OOF 概率 → Hosmer-Lemeshow + Youden 最优阈值。

    y 编码与训练一致（pd.Categorical codes，正类 = code 1）；仅二分类适用。
    """
    if not ranking:
        return None
    top_key = ranking[0]
    oof = _read_parquet(storage, f"runs/{run_id}/oof_{top_key}.parquet")
    target = _read_parquet(storage, f"runs/{run_id}/target.parquet")
    if oof is None or target is None or target["label"].nunique() != 2:
        return None
    if "oof" in oof.columns:
        p = oof["oof"].to_numpy(dtype=float)
    elif "oof_1" in oof.columns:
        p = oof["oof_1"].to_numpy(dtype=float)
    else:
        return None
    y = pd.Categorical(target["label"]).codes.astype(float)
    if len(y) != len(p):
        return None
    return {
        "model_key": top_key,
        "hosmer_lemeshow": hosmer_lemeshow_test(y, p),
        "optimal_threshold": compute_optimal_threshold(y, p, method="youden"),
    }


_SCREENING_MAX_ROWS = 20  # 报告内单因素筛选表行数上限（按 p 值升序截取）


def _insight_payload(db: Any, version: DatasetVersion | None) -> dict[str, Any] | None:
    """阶段 A DatasetInsight.payload（无体检 → None）。summary/supplement_plan 共用此源。"""
    if version is None:
        return None
    insight = (
        db.execute(
            select(DatasetInsight)
            .where(DatasetInsight.dataset_version_id == version.id)
            .order_by(DatasetInsight.created_at.desc())
        )
        .scalars()
        .first()
    )
    if insight is None or not insight.payload:
        return None
    return dict(insight.payload)


def _run_with_target(storage: Any, run: AnalysisRun) -> pd.DataFrame | None:
    """raw_features + 结局列（原名）合并表；缺产物 → None。"""
    raw = _read_parquet(storage, f"runs/{run.id}/raw_features.parquet")
    target = _read_parquet(storage, f"runs/{run.id}/target.parquet")
    if raw is None or target is None:
        return None
    df = raw.copy()
    target_cfg = (run.preprocess_config or {}).get("target") or {}
    if run.task_type == "survival":
        time_col = str(target_cfg.get("time_col") or "time")
        event_col = str(target_cfg.get("event_col") or "event")
        df[time_col] = target["time"].to_numpy()
        df[event_col] = target["event"].to_numpy()
    else:
        label_col = str(target_cfg.get("label_col") or "label")
        df[label_col] = target["label"].to_numpy()
    return df


def _screening_payload(storage: Any, run: AnalysisRun) -> dict[str, Any] | None:
    """P3：单因素筛选表进报告（真实检验；与 T6.10 API 同一引擎）。"""
    df = _run_with_target(storage, run)
    if df is None:
        return None
    target_cfg = (run.preprocess_config or {}).get("target") or {}
    try:
        result = univariate_screen(
            df,
            task_type=run.task_type,
            label_col=(
                str(target_cfg.get("label_col") or "label") if run.task_type != "survival" else None
            ),
            time_col=(
                str(target_cfg.get("time_col") or "time") if run.task_type == "survival" else None
            ),
            event_col=(
                str(target_cfg.get("event_col") or "event") if run.task_type == "survival" else None
            ),
        )
    except Exception as exc:
        logger.error("screening_failed", run_id=str(run.id), error=str(exc))
        return None
    if not result["rows"]:
        return None
    result["n_total_tested"] = len(result["rows"])
    result["rows"] = result["rows"][:_SCREENING_MAX_ROWS]
    return result


def _survival_analysis_payload(
    storage: Any, run_id: uuid.UUID, ranking: list[str]
) -> dict[str, Any] | None:
    """P3：风险集人数表（全样本）+ 推荐模型 OOF 风险中位分层 log-rank。"""
    target = _read_parquet(storage, f"runs/{run_id}/target.parquet")
    if target is None:
        return None
    times = target["time"].to_numpy(dtype=float).tolist()
    events = target["event"].to_numpy(dtype=int).tolist()
    at_risk = at_risk_table(times, events)
    logrank = None
    if ranking:
        oof = _read_parquet(storage, f"runs/{run_id}/oof_{ranking[0]}.parquet")
        if oof is not None and "oof" in oof.columns and len(oof) == len(target):
            logrank = median_risk_logrank(times, events, oof["oof"].to_numpy(dtype=float).tolist())
            if logrank is not None:
                logrank["model_key"] = ranking[0]
    if at_risk is None and logrank is None:
        return None
    return {"at_risk": at_risk, "logrank": logrank}


def _trim_diagnostics(diag: dict[str, Any] | None) -> dict[str, Any] | None:
    """LLM facts 用诊断子集：系数表/VIF 截断（控制 payload 体积，值仍为真实计算结果）。"""
    if not diag:
        return None
    trimmed = {k: v for k, v in diag.items() if k != "coefficients"}
    coeffs = diag.get("coefficients")
    if coeffs:
        trimmed["coefficients_top"] = list(coeffs)[:5]
    vif = diag.get("vif") or {}
    if vif.get("vif_values"):
        trimmed["vif"] = {
            "conclusion": vif.get("conclusion"),
            "vif_values": dict(list((vif.get("vif_values") or {}).items())[:10]),
        }
    return trimmed


def _interpretation_facts(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """报告解读 facts（T6.7）：全部由 payload 真实计算值组装，LLM 只做表达不做计算。"""
    comparison = payload.get("comparison") or {}
    recommendation = comparison.get("recommendation") or {}
    table = payload.get("table") or []
    if not comparison or not table:
        return {}
    task_type = (payload.get("run") or {}).get("task_type")
    perf_rows = [
        {
            "model_key": r.get("model_key"),
            "status": r.get("status"),
            "metrics": r.get("metrics"),
            "p_value_text": r.get("p_value_text"),
        }
        for r in table
    ]
    diagnostics = _trim_diagnostics(payload.get("diagnostics"))
    calibration = payload.get("calibration")

    facts: dict[str, dict[str, Any]] = {
        "model_comparison": {
            "task_type": task_type,
            "primary_metric": recommendation.get("primary_metric"),
            "ranking": comparison.get("ranking") or [],
            "top": recommendation.get("top") or [],
            "not_recommended": recommendation.get("not_recommended") or [],
            "performance": perf_rows,
        },
        "performance": {
            "task_type": task_type,
            "performance": perf_rows,
            "significance_note": payload.get("significance_note"),
            "diagnostics": diagnostics,
            "calibration": calibration,
        },
    }
    clinical: dict[str, Any] = {}
    for chart in comparison.get("charts") or []:
        if chart.get("kind") == "hr_forest":
            clinical["hazard_ratios"] = [
                {"model_key": m.get("model_key"), "rows": (m.get("rows") or [])[:5]}
                for m in (chart.get("data") or {}).get("models", [])
            ]
        if chart.get("kind") == "feature_importance":
            clinical["top_features"] = ((chart.get("data") or {}).get("features") or [])[:5]
    if diagnostics:
        clinical["diagnostics"] = diagnostics
    if calibration:
        clinical["calibration"] = calibration
    if clinical:
        facts["clinical_interpretation"] = clinical
    return facts


def _llm_interpretations(db: Any, payload: dict[str, Any]) -> dict[str, str] | None:
    """T6.7：报告解读段落（分功能开关门控；关闭/失败 → None，context 模板拼句兜底）。"""
    cfg = get_llm_config_sync(db)
    switch = cfg.feature_switches.get("report_interpretation", "off")
    if switch == "off":
        return None
    facts = _interpretation_facts(payload)
    if not facts:
        return None
    service = init_llm_service_from_runtime(cfg)
    paragraphs = llm_tasks.generate_report_interpretations(service, facts, switch, cfg.temperature)
    return paragraphs or None


def assemble_report_payload(db: Any, run: AnalysisRun) -> dict[str, Any]:
    """DB + 存储产物 → ReportContext payload（docs/10 §3 单一事实源）。"""
    version = db.get(DatasetVersion, run.dataset_version_id)
    dataset = db.get(Dataset, version.dataset_id) if version is not None else None
    quality = None
    if version is not None:
        quality = (
            db.execute(
                select(QualityReport)
                .where(QualityReport.dataset_version_id == version.id)
                .order_by(QualityReport.created_at.desc())
            )
            .scalars()
            .first()
        )
    snapshot = (
        db.execute(select(PreprocessSnapshot).where(PreprocessSnapshot.run_id == run.id))
        .scalars()
        .first()
    )
    results = db.execute(select(ModelResult).where(ModelResult.run_id == run.id)).scalars().all()
    comparison = db.execute(select(Comparison).where(Comparison.run_id == run.id)).scalars().first()

    storage = storage_from_settings()
    ranking = list(comparison.ranking) if comparison and comparison.ranking else []
    insight = _insight_payload(db, version)
    eda_summary = (insight or {}).get("summary")
    payload: dict[str, Any] = {
        "run": {
            "task_type": run.task_type,
            "status": run.status,
            "selected_models": list(run.selected_models or []),
            "created_at": str(run.created_at),
            "finished_at": str(run.finished_at) if run.finished_at else None,
        },
        "dataset": {"name": dataset.name if dataset else None},
        "target_summary": _target_summary(storage, run.id, run.task_type),
        "validation": (run.preprocess_config or {}).get("validation"),
        "task_detection": run.task_detection,
        "quality_report": (
            {
                "status": quality.status,
                "blockers": quality.blockers,
                "warnings": quality.warnings,
                "issues": quality.issues,
                "column_profiles": quality.column_profiles,
            }
            if quality
            else None
        ),
        "transform_log": list(version.transform_log) if version else [],
        "preprocess_steps": list(snapshot.steps) if snapshot else None,
        "input_hash": snapshot.input_hash if snapshot else None,
        "table": _enhanced_table(results, comparison, run.task_type),
        # T6.3：基线特征表 / 回归诊断 / 分类校准（真实计算；缺产物 → None → 不适用）
        "baseline_table": _baseline_table_payload(storage, run),
        # P3：数据体检摘要 / 单因素筛选 / 生存补充统计（真实计算；缺产物 → None）
        "eda_summary": (
            [str(line) for line in eda_summary]
            if isinstance(eda_summary, list) and eda_summary
            else None
        ),
        # T6.14：体检缺口建议 → 报告动态局限性数据源（无体检或旧记录 → None）
        "supplement_plan": (insight or {}).get("supplement_plan"),
        "screening": _screening_payload(storage, run),
        "survival_analysis": (
            _survival_analysis_payload(storage, run.id, ranking)
            if run.task_type == "survival"
            else None
        ),
        "diagnostics": (
            _regression_diagnostics(storage, run.id, ranking)
            if run.task_type == "regression"
            else None
        ),
        "calibration": (
            _classification_calibration(storage, run.id, ranking)
            if run.task_type == "classification"
            else None
        ),
        "significance_note": add_statistical_significance_note() if comparison else None,
        "comparison": (
            {
                "ranking": comparison.ranking,
                "recommendation": comparison.recommendation,
                "charts": comparison.comparison_charts,
            }
            if comparison
            else None
        ),
        "software": _software_versions(),
    }
    # T6.7：LLM 解读段落（真实指标 facts；关闭或失败 → None，模板拼句兜底）
    payload["llm_interpretations"] = _llm_interpretations(db, payload)
    return payload


def _embed_images(context: dict[str, Any]) -> None:
    """各章节图表 JSON → PNG base64 注入（单数据源：与前端 ECharts 同一 JSON）。"""
    for section in context["sections"]:
        charts = section.get("data", {}).get("charts")
        if not charts:
            continue
        for chart in charts:
            b64 = chart_to_b64(chart)
            if b64:
                chart["image_b64"] = b64


def build_context(db: Any, run: AnalysisRun) -> dict[str, Any]:
    """装配 ReportContext 并注入 PNG base64（html/pdf/markdown/docx 共用）。"""
    context = build_report_context(assemble_report_payload(db, run))
    _embed_images(context)
    return context


def render_report_html(db: Any, run: AnalysisRun) -> str:
    """装配 + 渲染主入口（worker 与契约测试共用）。"""
    return render_html(build_context(db, run))


@celery_app.task(name="app.workers.report_tasks.generate_report")
def generate_report(report_id: str) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        report = db.get(Report, uuid.UUID(report_id))
        if report is None or report.status != "PENDING":
            return  # 幂等：重复投递/已终态直接返回
        try:
            run = db.get(AnalysisRun, report.run_id)
            if run is None or run.status != "COMPLETED":
                raise ValueError("仅 COMPLETED 运行可生成报告")
            report.template_key = TEMPLATE_KEY
            report.template_version = TEMPLATE_VERSION
            supported = ("html", "pdf", "markdown", "docx")
            if report.format in supported:
                context = build_context(db, run)
                # docs/10 §3：HTML 主产物派生 PDF/Markdown；docx 由同一 Context 填充
                if report.format == "docx":
                    payload = context_to_docx(context)
                elif report.format == "html":
                    # docs/10 §2.2：仅 HTML 产物重点表默认折叠；派生格式全展开
                    payload = render_html(context, collapsible=True).encode("utf-8")
                else:
                    html = render_html(context)
                    if report.format == "pdf":
                        payload = html_to_pdf(html)
                    else:
                        payload = html_to_markdown(html).encode("utf-8")
                storage = storage_from_settings()
                uri = storage.put(
                    f"reports/{report_id}/report.{report.format}",
                    io.BytesIO(payload),
                    len(payload),
                    content_type=_CONTENT_TYPES[report.format],
                )
                report.storage_uri = str(uri)
            else:
                raise ValueError(f"格式 {report.format} 不支持（允许：{supported}）")
            report.status = "READY"
            db.commit()
            logger.info("report_ready", report_id=report_id, format=report.format)
        except Exception as exc:
            db.rollback()
            report.status = "FAILED"
            db.commit()
            logger.error("report_failed", report_id=report_id, error=str(exc))


def key_of_report(report: Report) -> str:
    """Report.storage_uri → 存储 key（下载/预览用）。"""
    return key_from_uri(str(report.storage_uri))
