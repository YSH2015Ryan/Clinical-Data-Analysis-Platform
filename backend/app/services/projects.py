"""项目服务：CRUD + 项目级隔离（docs/12 §2.2）。

隔离纪律：所有 project-scoped 查询强制 owner_id == current_user.id（admin 除外），
越权一律返回 None（api 层映射 404，不泄露资源存在性）。
"""

import base64
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AnalysisRun, Dataset, DatasetVersion, Project, Report
from app.schemas.auth import CurrentUser
from app.schemas.project import ProjectCreate


def _visible_to(stmt, user: CurrentUser):  # type: ignore[no-untyped-def]
    if user.role != "admin":
        stmt = stmt.where(Project.owner_id == user.id)
    return stmt


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"offset:{offset}".encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        prefix, _, value = raw.partition("offset:")
        if prefix or not value.isdigit():
            return 0
        return int(value)
    except Exception:
        return 0


async def list_projects(
    db: AsyncSession, user: CurrentUser, cursor: str | None, limit: int
) -> tuple[list[Project], str | None]:
    offset = _decode_cursor(cursor) if cursor else 0
    stmt = (
        select(Project)
        .where(Project.deleted_at.is_(None))
        .order_by(Project.created_at.desc(), Project.id)
        .offset(offset)
        .limit(limit + 1)
    )
    stmt = _visible_to(stmt, user)
    rows: list[Project] = list((await db.execute(stmt)).scalars().all())
    items: list[Project] = rows[:limit]
    next_cursor: str | None = None
    if len(rows) > limit:
        next_cursor = _encode_cursor(offset + limit)
    return items, next_cursor


async def create_project(db: AsyncSession, user: CurrentUser, body: ProjectCreate) -> Project:
    project = Project(owner_id=user.id, name=body.name, description=body.description)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(db: AsyncSession, user: CurrentUser, project_id: uuid.UUID) -> Project | None:
    stmt = select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    stmt = _visible_to(stmt, user)
    return (await db.execute(stmt)).scalar_one_or_none()


async def soft_delete_project(
    db: AsyncSession, user: CurrentUser, project_id: uuid.UUID
) -> Project | None:
    project = await get_project(db, user, project_id)
    if project is None:
        return None
    project.deleted_at = datetime.now(UTC)
    await db.commit()
    return project


async def storage_keys_for_project(db: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """收集项目所有对象键，供事务提交后的补偿清理任务使用。"""
    keys: set[str] = {f"datasets/{project_id}/"}
    datasets = (
        (await db.execute(select(Dataset).where(Dataset.project_id == project_id))).scalars().all()
    )
    for dataset in datasets:
        if dataset.storage_uri:
            from app.services.storage import key_from_uri

            keys.add(key_from_uri(dataset.storage_uri))
        versions = (
            (
                await db.execute(
                    select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
                )
            )
            .scalars()
            .all()
        )
        for version in versions:
            if version.storage_uri:
                from app.services.storage import key_from_uri

                keys.add(key_from_uri(version.storage_uri))
    runs = (
        (await db.execute(select(AnalysisRun).where(AnalysisRun.project_id == project_id)))
        .scalars()
        .all()
    )
    for run in runs:
        keys.add(f"runs/{run.id}/")
        reports = (await db.execute(select(Report).where(Report.run_id == run.id))).scalars().all()
        for report in reports:
            if report.storage_uri:
                from app.services.storage import key_from_uri

                keys.add(key_from_uri(report.storage_uri))
    return sorted(keys)
