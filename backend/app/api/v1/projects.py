"""项目端点（冻结契约 docs/14 §3 + 变更记录 2026-07-29 DELETE）。"""

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.errors import not_found
from app.db import get_db
from app.schemas.auth import CurrentUser
from app.schemas.project import Project, ProjectCreate, ProjectPage
from app.services import projects as project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectPage)
async def list_projects(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectPage:
    items, next_cursor = await project_service.list_projects(db, user, cursor, limit)
    return ProjectPage(
        items=[
            Project(id=p.id, name=p.name, description=p.description, created_at=p.created_at)
            for p in items
        ],
        next_cursor=next_cursor,
    )


@router.post("", response_model=Project, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await project_service.create_project(db, user, body)
    return Project(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await project_service.soft_delete_project(db, user, project_id)
    if project is None:
        raise not_found("project", str(project_id))
    return Response(status_code=204)
