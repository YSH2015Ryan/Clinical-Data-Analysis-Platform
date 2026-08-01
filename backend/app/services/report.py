"""报告服务（docs/10 §4；冻结契约 docs/14 /reports、/analysis-runs/{id}/reports）。

创建：校验 run 归属与 COMPLETED 状态 → 落库 PENDING → 返回（worker 异步渲染）；
下载：READY → 预签名 URL（本地模式为文件路径，仅开发用）；PENDING → REPORT_NOT_READY。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.models.entities import Report
from app.schemas.auth import CurrentUser
from app.schemas.report import ReportCreate
from app.services.analysis import get_run
from app.services.storage import key_from_uri, storage_from_settings


async def create_report(db: AsyncSession, user: CurrentUser, body: ReportCreate) -> Report:
    run = await get_run(db, user, body.run_id)  # 归属校验复用分析服务
    if run.status != "COMPLETED":
        raise AppError(
            "INVALID_RUN_STATE", 400, f"运行状态 {run.status} 不可生成报告（须 COMPLETED）"
        )
    report = Report(
        run_id=run.id, format=body.format, template_key=body.template_key, created_by=user.id
    )
    db.add(report)
    await db.flush()
    return report


async def list_run_reports(db: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> list[Report]:
    await get_run(db, user, run_id)  # 归属校验
    return list(
        (
            await db.execute(
                select(Report).where(Report.run_id == run_id).order_by(Report.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def get_report(db: AsyncSession, user: CurrentUser, report_id: uuid.UUID) -> Report:
    report = (await db.execute(select(Report).where(Report.id == report_id))).scalar_one_or_none()
    if report is None:
        raise not_found("report", str(report_id))
    await get_run(db, user, report.run_id)  # 经 run → project 归属校验
    return report


async def get_download_url(db: AsyncSession, user: CurrentUser, report_id: uuid.UUID) -> str:
    report = await get_report(db, user, report_id)
    if report.status != "READY" or not report.storage_uri:
        raise AppError("REPORT_NOT_READY", 400, "报告仍在生成中，不可下载")
    return storage_from_settings().presign_download(key_from_uri(str(report.storage_uri)))
