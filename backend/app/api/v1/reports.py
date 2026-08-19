"""报告端点（冻结契约 docs/14 §3 /reports；docs/10 §4 预览与下载）。

POST /reports → 202（落库 PENDING + dispatch generate_report）；
GET /analysis-runs/{run_id}/reports → 该运行的报告历史列表；
GET /reports/{report_id} → 报告详情（前端轮询状态用）；
GET /reports/{report_id}/download → 302 重定向预签名 URL。
"""

import uuid
from datetime import datetime
from typing import Protocol

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.errors import AppError
from app.db import get_db
from app.schemas.auth import CurrentUser
from app.schemas.report import ReportCreate, ReportOut
from app.services import audit as audit_service
from app.services import report as report_service
from app.workers.report_tasks import generate_report

router = APIRouter(tags=["reports"])


class _ReportLike(Protocol):
    """ORM Report 结构协议（api 层不直接 import models —— 分层纪律）。"""

    id: uuid.UUID
    run_id: uuid.UUID
    status: str
    format: str
    template_key: str
    created_at: datetime


def _out(report: _ReportLike) -> ReportOut:
    return ReportOut(
        id=report.id,
        run_id=report.run_id,
        status=report.status,
        format=report.format,
        template_key=report.template_key,
        created_at=report.created_at,
    )


@router.post("/reports", status_code=202, response_model=ReportOut)
async def create_report(
    body: ReportCreate,
    user: CurrentUser = Depends(require_role("researcher")),
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    report = await report_service.create_report(db, user, body)
    await audit_service.record(
        db,
        "report.create",
        user_id=user.id,
        resource_type="report",
        resource_id=report.id,
        detail={"run_id": str(body.run_id), "format": body.format},
    )
    await db.commit()  # 先落库：worker 以独立会话读取 report 行
    try:
        generate_report.apply_async(args=[str(report.id)])
    except Exception as exc:
        report.status = "FAILED"
        await db.commit()
        raise AppError("TASK_DISPATCH_FAILED", 503, "报告任务暂时无法排队，请稍后重试") from exc
    return _out(report)


@router.get("/analysis-runs/{run_id}/reports", response_model=list[ReportOut])
async def list_run_reports(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReportOut]:
    return [_out(r) for r in await report_service.list_run_reports(db, user, run_id)]


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    return _out(await report_service.get_report(db, user, report_id))


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    url = await report_service.get_download_url(db, user, report_id)
    return RedirectResponse(url=url, status_code=302)
