"""数据准备服务（docs/05 §8、docs/14 §3 preparation 端点）。

纪律：api 不直接读存储/引擎，统一经本服务；两数据集须同项目且归属当前用户
（复用 datasets.get_dataset 的项目级隔离，越权 → None → api 层 404）。
"""

import uuid

import pandas as pd
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, not_found
from app.engines import parser
from app.engines.preparation import PrepPreview, scan
from app.models.entities import Dataset, PreparationJob, Project
from app.schemas.auth import CurrentUser
from app.schemas.preparation import PreparationDecisions
from app.services.datasets import get_dataset
from app.services.storage import StorageBackend, key_from_uri


def _load_df(storage: StorageBackend, dataset: Dataset) -> pd.DataFrame:
    raw = storage.get(key_from_uri(dataset.storage_uri))
    return parser.parse(raw, dataset.source_type).df


async def _get_pair(
    db: AsyncSession, user: CurrentUser, lab_dataset_id: uuid.UUID, diag_dataset_id: uuid.UUID
) -> tuple[Dataset, Dataset]:
    lab = await get_dataset(db, user, lab_dataset_id)
    if lab is None:
        raise not_found("dataset", str(lab_dataset_id))
    diag = await get_dataset(db, user, diag_dataset_id)
    if diag is None:
        raise not_found("dataset", str(diag_dataset_id))
    if lab.project_id != diag.project_id:
        raise AppError(code="VALIDATION_ERROR", status=400, message="化验表与诊断表须属于同一项目")
    return lab, diag


async def preview(
    db: AsyncSession,
    storage: StorageBackend,
    user: CurrentUser,
    lab_dataset_id: uuid.UUID,
    diag_dataset_id: uuid.UUID,
) -> PrepPreview:
    """扫描两表：列识别 + 诊断词条统计 + 建议默认值（供决策表单预填）。"""
    lab, diag = await _get_pair(db, user, lab_dataset_id, diag_dataset_id)
    return scan(_load_df(storage, lab), _load_df(storage, diag))


async def create_job(
    db: AsyncSession,
    user: CurrentUser,
    lab_dataset_id: uuid.UUID,
    diag_dataset_id: uuid.UUID,
    decisions: PreparationDecisions,
) -> PreparationJob:
    """创建 PENDING 任务；调用方负责 commit 与入队 worker。"""
    lab, _diag = await _get_pair(db, user, lab_dataset_id, diag_dataset_id)
    job = PreparationJob(
        project_id=lab.project_id,
        lab_dataset_id=lab_dataset_id,
        diag_dataset_id=diag_dataset_id,
        decisions=decisions.model_dump(mode="json"),
        status="PENDING",
        created_by=user.id,
    )
    db.add(job)
    await db.flush()
    return job


def _owner_filter(user: CurrentUser) -> ColumnElement[bool]:
    if user.role == "admin":
        return true()
    return Project.owner_id == user.id


async def get_job(db: AsyncSession, user: CurrentUser, job_id: uuid.UUID) -> PreparationJob | None:
    stmt = (
        select(PreparationJob)
        .join(Project, PreparationJob.project_id == Project.id)
        .where(
            PreparationJob.id == job_id,
            Project.deleted_at.is_(None),
            _owner_filter(user),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()
