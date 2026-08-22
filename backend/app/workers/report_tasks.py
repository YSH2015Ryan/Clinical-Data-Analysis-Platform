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
from app.engines.reporting.chart_png import chart_to_b64
from app.engines.reporting.context import build_report_context
from app.engines.reporting.docx_export import context_to_docx
from app.engines.reporting.markdown_export import html_to_markdown
from app.engines.reporting.pdf import html_to_pdf
from app.engines.reporting.render import TEMPLATE_KEY, TEMPLATE_VERSION, render_html
from app.models.entities import (
    AnalysisRun,
    Comparison,
    Dataset,
    DatasetVersion,
    ModelResult,
    PreprocessSnapshot,
    QualityReport,
    Report,
)
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
    return {
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
        "table": [
            {
                "model_key": r.model_key,
                "status": r.status,
                "metrics": r.metrics,
                "duration_ms": r.duration_ms,
            }
            for r in results
        ],
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
