"""数据准备任务（docs/05 §8）：长表+诊断表 → 宽表数据集（source_type=prepared）。

幂等纪律：COMPLETED 任务重入直接返回；产物数据集每次运行新建（与任务一一对应）。
失败置 FAILED 并记录中文错误（引擎 ValueError 已中文化）。
"""

import hashlib
import io
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines import parser, validation
from app.engines.preparation import PrepDecisions, prepare
from app.models.entities import Dataset, DatasetVersion, PreparationJob, QualityReport
from app.services.storage import key_from_uri, storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)


@celery_app.task(name="app.workers.preparation_tasks.run_preparation")
def run_preparation(job_id: str) -> None:
    session_factory = get_sync_session_factory()
    with session_factory() as db:
        job = db.execute(
            select(PreparationJob).where(PreparationJob.id == uuid.UUID(job_id))
        ).scalar_one_or_none()
        if job is None:
            logger.warning("run_preparation_not_found", job_id=job_id)
            return
        if job.status == "COMPLETED":
            return  # 幂等：重投不重复产出
        job.status = "RUNNING"
        db.commit()
        try:
            result_id, summary = _execute(db, job)
            job.status = "COMPLETED"
            job.result_dataset_id = result_id
            job.summary = summary
            job.finished_at = datetime.now(UTC)
            db.commit()
            logger.info(
                "preparation_completed",
                job_id=job_id,
                result_dataset_id=str(result_id),
                wide_rows=summary.get("wide_rows"),
                features=summary.get("features"),
            )
        except Exception as exc:
            job.status = "FAILED"
            job.error = str(exc)[:2000]
            job.finished_at = datetime.now(UTC)
            db.commit()
            logger.error("preparation_failed", job_id=job_id, error=str(exc)[:200])


def _load_df(storage: Any, dataset: Dataset) -> pd.DataFrame:
    raw = storage.get(key_from_uri(dataset.storage_uri))
    return parser.parse(raw, dataset.source_type).df


def _execute(db: Session, job: PreparationJob) -> tuple[uuid.UUID, dict[str, Any]]:
    storage = storage_from_settings()
    lab = db.execute(select(Dataset).where(Dataset.id == job.lab_dataset_id)).scalar_one()
    diag = db.execute(select(Dataset).where(Dataset.id == job.diag_dataset_id)).scalar_one()

    dec = dict(job.decisions)
    dec["outcome_terms"] = tuple(dec["outcome_terms"])
    result = prepare(_load_df(storage, lab), _load_df(storage, diag), PrepDecisions(**dec))

    payload = result.wide.to_csv(index=False).encode("utf-8")
    dataset = Dataset(
        project_id=job.project_id,
        name=f"数据准备宽表_{lab.name}",
        source_type="prepared",
        storage_uri="",
        file_hash=hashlib.sha256(payload).hexdigest(),
        file_size=len(payload),
        encoding="utf-8",
        status="VALIDATED",
    )
    db.add(dataset)
    db.flush()
    key = f"datasets/{job.project_id}/{dataset.id}/prepared_wide.csv"
    uri = storage.put(key, io.BytesIO(payload), len(payload))
    dataset.storage_uri = uri
    version = DatasetVersion(dataset_id=dataset.id, version_no=1, storage_uri=uri)
    db.add(version)
    db.flush()

    # 产物即入库即校验：预览/画像/质量报告齐备，可直接进入分析流程
    report = validation.validate(result.wide, raw_columns=[str(c) for c in result.wide.columns])
    dataset.preview = parser.preview_json(result.wide)
    dataset.column_profile = report.column_profiles
    dataset.status = "FAILED" if report.status == "FAILED" else "VALIDATED"
    db.add(
        QualityReport(
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            status=report.status,
            blockers=report.blockers,
            warnings=report.warnings,
            issues=[i.to_dict() for i in report.issues],
            column_profiles=report.column_profiles,
        )
    )
    db.flush()
    return dataset.id, result.summary
