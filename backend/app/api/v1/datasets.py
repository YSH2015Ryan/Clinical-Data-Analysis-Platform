"""数据集端点（冻结契约 docs/14 §3）。

上传：POST /projects/{id}/datasets → 202；
查询（T2.5）：GET /projects/{id}/datasets 列表、GET /datasets/{id} 详情、
GET /datasets/{id}/quality-report 最新质量报告。
"""

import uuid

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.db import get_db
from app.schemas.auth import CurrentUser
from app.schemas.dataset import DatasetAccepted, DatasetDetail, DatasetPage, QualityReport
from app.services import audit as audit_service
from app.services import datasets as dataset_service
from app.services import projects as project_service
from app.services.storage import storage_from_settings
from app.workers.dataset_tasks import validate_dataset

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])
dataset_router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("", status_code=202, response_model=DatasetAccepted)
async def upload_dataset(
    project_id: uuid.UUID,
    file: UploadFile,
    name: str | None = Form(default=None),
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> DatasetAccepted:
    project = await project_service.get_project(db, user, project_id)
    if project is None:
        raise not_found("project", str(project_id))
    if file.filename is None:
        raise AppError(code="VALIDATION_ERROR", status=400, message="缺少文件名")

    settings = get_settings()
    dataset = await dataset_service.ingest_upload(
        db,
        storage_from_settings(),
        project_id=project_id,
        filename=name or file.filename,
        stream=file.file,
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        declared_size=file.size,
    )
    await audit_service.record(
        db,
        "dataset.upload",
        user_id=user.id,
        resource_type="dataset",
        resource_id=dataset.id,
        detail={"filename": file.filename, "size": dataset.file_size},
    )
    await db.commit()

    validate_dataset.delay(str(dataset.id))
    return DatasetAccepted(dataset_id=dataset.id)


@router.get("", response_model=DatasetPage)
async def list_datasets(
    project_id: uuid.UUID,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetPage:
    project = await project_service.get_project(db, user, project_id)
    if project is None:
        raise not_found("project", str(project_id))
    items, next_cursor = await dataset_service.list_datasets(db, user, project_id, cursor, limit)
    return DatasetPage(
        items=[DatasetDetail.model_validate(d, from_attributes=True) for d in items],
        next_cursor=next_cursor,
    )


@dataset_router.get("/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetDetail:
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    return DatasetDetail.model_validate(dataset, from_attributes=True)


@dataset_router.get("/{dataset_id}/quality-report", response_model=QualityReport)
async def get_quality_report(
    dataset_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QualityReport:
    dataset = await dataset_service.get_dataset(db, user, dataset_id)
    if dataset is None:
        raise not_found("dataset", str(dataset_id))
    report = await dataset_service.get_latest_report(db, dataset_id)
    if report is None:
        raise not_found("report", str(dataset_id))
    return QualityReport.model_validate(report, from_attributes=True)
