"""报告 API schemas（docs/14 ReportCreate/Report，契约冻结 v1.0-frozen）。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ReportFormat = Literal["pdf", "html", "markdown", "docx"]


class ReportCreate(BaseModel):
    run_id: uuid.UUID
    format: ReportFormat
    template_key: str = "clinical_report_zh"


class ReportOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    status: str
    format: str
    template_key: str
    created_at: datetime
