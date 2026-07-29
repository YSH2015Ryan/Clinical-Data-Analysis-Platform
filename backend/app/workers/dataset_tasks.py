"""数据集校验任务（docs/05 §2 流水线：解析 → 画像 → 规则 → 报告）。

T2.2：解析 + 预览入库；T2.3：列类型/语义（engines/columns，由校验调用）；
T2.4：13 规则校验 + 质量报告落库 + 状态流转 VALIDATED/FAILED。
幂等纪律：任务可重入，重跑覆盖最新报告；失败置 FAILED 并记录 RV001。
"""

import uuid

from sqlalchemy import select

from app.core.logging import get_logger
from app.engines import parser, validation
from app.models.entities import Dataset, DatasetVersion, QualityReport
from app.services.storage import storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)


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
            raw = storage_from_settings().get(_storage_key_from_uri(dataset.storage_uri))
            result = parser.parse(raw, dataset.source_type)
            report = validation.validate(result.df, raw_columns=result.raw_columns)
            dataset.encoding = result.encoding
            dataset.preview = parser.preview_json(result.df)
            dataset.column_profile = report.column_profiles
            dataset.status = "FAILED" if report.status == "FAILED" else "VALIDATED"
            db.add(_quality_report(dataset, version, report))
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
    dataset: Dataset, version: DatasetVersion, report: validation.ValidationReport
) -> QualityReport:
    return QualityReport(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        status=report.status,
        blockers=report.blockers,
        warnings=report.warnings,
        issues=[i.to_dict() for i in report.issues],
        column_profiles=report.column_profiles,
    )


def _encoding_hint(raw: bytes) -> str | None:
    try:
        return parser.detect_encoding(raw)
    except Exception:
        return None


def _storage_key_from_uri(uri: str) -> str:
    """S3 uri (s3://bucket/key) → key；local 模式 uri 即路径，key 取相对部分。"""
    if uri.startswith("s3://"):
        return uri.split("/", 3)[3]
    # local: <root>/<key>，key 以 datasets/ 开头
    idx = uri.find("datasets/")
    return uri[idx:] if idx >= 0 else uri
