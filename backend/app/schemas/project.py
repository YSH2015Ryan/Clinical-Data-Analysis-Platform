"""项目 schema（契约同源：docs/14 §3 ProjectCreate/Project/ProjectPage）。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class Project(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime


class ProjectPage(BaseModel):
    items: list[Project]
    next_cursor: str | None = None
