"""数据集校验任务（docs/05 §2 流水线：解析 → 画像 → 规则 → 报告）。

T2.2：解析 + 预览入库；T2.3：列类型/语义（engines/columns，由校验调用）；
T2.4：13 规则校验 + 质量报告落库 + 状态流转 VALIDATED/FAILED。
幂等纪律：任务可重入，重跑覆盖最新报告；失败置 FAILED 并记录 RV001。
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.engines import parser, validation
from app.models.entities import Dataset, DatasetVersion, QualityReport
from app.services.storage import key_from_uri, storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)
_SENSITIVE_HINTS = (
    "name",
    "姓名",
    "patient",
    "患者",
    "mrn",
    "身份证",
    "phone",
    "电话",
    "email",
    "地址",
)


@celery_app.task(name="app.workers.dataset_tasks.validate_dataset")
def validate_dataset(dataset_id: str) -> None:
    session_factory = get_sync_session_factory()
    with session_factory() as db:
        dataset = db.execute(
            select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
        ).scalar_one_or_none()
        if dataset is None:
            logger.warning("validate_dataset_not_found", dataset_id=dataset_id)
            return
        version = db.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.version_no.desc())
            .limit(1)
        ).scalar_one_or_none()
        if version is None:
            logger.error("validate_dataset_no_version", dataset_id=dataset_id)
            return
        raw: bytes | None = None
        try:
            raw = storage_from_settings().get(key_from_uri(dataset.storage_uri))
            result = parser.parse(raw, dataset.source_type)
            report = validation.validate(result.df, raw_columns=result.raw_columns)
            
            # Phase 6 T6.6: 智能任务推荐（使用 LLM 分析数据集适合的分析类型）
            task_recommendation = None
            try:
                from app.services.llm import get_llm_service
                from app.engines.intelligent_task_advisor import IntelligentTaskAdvisor
                
                llm_service = get_llm_service()
                if llm_service.is_available():
                    advisor = IntelligentTaskAdvisor(llm_service)
                    task_recommendation = advisor.analyze_dataset(result.df, report.column_profiles)
                    logger.info(
                        "intelligent_task_recommendation",
                        dataset_id=dataset_id,
                        recommended_tasks=task_recommendation.recommended_tasks,
                        can_start_modeling=task_recommendation.can_start_modeling
                    )
            except Exception as llm_exc:
                logger.warning(
                    "task_recommendation_failed",
                    dataset_id=dataset_id,
                    error=str(llm_exc)
                )
            
            dataset.encoding = result.encoding
            dataset.preview = _redact_preview(parser.preview_json(result.df))
            dataset.column_profile = parser.normalize_json_value(report.column_profiles)
            dataset.status = "FAILED" if report.status == "FAILED" else "VALIDATED"
            db.add(_quality_report(dataset, version, report, task_recommendation))
            db.commit()
            logger.info(
                "dataset_validated",
                dataset_id=dataset_id,
                rows=len(result.df),
                cols=len(result.df.columns),
                encoding=result.encoding,
                report_status=report.status,
                blockers=report.blockers,
                warnings=report.warnings,
            )
        except Exception as exc:
            # RV001 文件无法解析：阻塞级 + 修正建议（docs/05 §3）
            db.rollback()
            issue = validation.parse_error_issue(_encoding_hint(raw) if raw else None)
            dataset.status = "FAILED"
            db.add(
                QualityReport(
                    dataset_id=dataset.id,
                    dataset_version_id=version.id,
                    status="FAILED",
                    blockers=1,
                    warnings=0,
                    issues=[issue.to_dict()],
                    column_profiles=[],
                )
            )
            db.commit()
            logger.error("dataset_parse_failed", dataset_id=dataset_id, error=type(exc).__name__)


def _quality_report(
    dataset: Dataset, 
    version: DatasetVersion, 
    report: validation.ValidationReport,
    task_recommendation: Any = None
) -> QualityReport:
    """构建质量报告，包含智能任务推荐（如果可用）"""
    
    # 将任务推荐添加到 issues 中（作为 info 级别）
    issues = [i.to_dict() for i in report.issues]
    
    if task_recommendation:
        # 添加任务推荐信息
        recommendation_issue = {
            "rule_id": "AI_RECOMMEND",
            "severity": "info",
            "message": "智能任务推荐",
            "column": None,
            "suggestion": task_recommendation.overall_assessment,
            "detail": {
                "recommended_tasks": task_recommendation.recommended_tasks,
                "recommended_targets": task_recommendation.recommended_targets,
                "unsuitable_tasks": task_recommendation.unsuitable_tasks,
                "eda_suggestions": task_recommendation.eda_suggestions,
                "can_start_modeling": task_recommendation.can_start_modeling
            },
            "affected_rows": None
        }
        issues.append(recommendation_issue)
    
    return QualityReport(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        status=report.status,
        blockers=report.blockers,
        warnings=report.warnings,
        issues=issues,
        column_profiles=parser.normalize_json_value(report.column_profiles),
    )


def _encoding_hint(raw: bytes) -> str | None:
    try:
        return parser.detect_encoding(raw)
    except Exception:
        return None


def _redact_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """预览只用于交互提示，疑似直接标识符不应进入数据库或浏览器。"""
    columns = [str(c) for c in preview.get("columns", [])]
    sensitive = {
        i
        for i, column in enumerate(columns)
        if any(hint in column.lower() for hint in _SENSITIVE_HINTS)
    }
    rows = [
        ["[REDACTED]" if i in sensitive else value for i, value in enumerate(row)]
        for row in preview.get("rows", [])
    ]
    return {**preview, "rows": rows}
