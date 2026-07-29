"""数据集上传端点（冻结契约 docs/14 §3：POST /projects/{id}/datasets → 202）。"""

import uuid

from fastapi import APIRouter, Depends, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.db import get_db
from app.schemas.auth import CurrentUser
from app.schemas.dataset import DatasetAccepted
from app.services import audit as audit_service
from app.services import datasets as dataset_service
from app.services import projects as project_service
from app.services.storage import storage_from_settings
from app.workers.dataset_tasks import validate_dataset

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])


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
