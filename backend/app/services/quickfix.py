"""Quick Fix 服务（docs/05 §5、docs/14 §3 POST /datasets/{id}/quick-fix）。

纪律：修复产生新 DatasetVersion（新存储 key），原文件不变；修复后重新校验
并刷新 dataset.preview/column_profile/status（影响预览准确 — T2.6 DoD）。
"""

import io
import uuid

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines import parser, quickfix, validation
from app.models.entities import Dataset, DatasetVersion, QualityReport
from app.services.storage import StorageBackend, key_from_uri


async def apply_quick_fix(
    db: AsyncSession,
    storage: StorageBackend,
    *,
    dataset: Dataset,
    actions: list[quickfix.QuickFixAction],
) -> DatasetVersion:
    raw = storage.get(key_from_uri(dataset.storage_uri))
    result = parser.parse(raw, dataset.source_type)
    new_df, log = quickfix.apply_actions(result.df, actions)

    version_no = await _next_version_no(db, dataset.id)
    uri = _write_new_version(storage, dataset, version_no, new_df)
    version = DatasetVersion(
        dataset_id=dataset.id, version_no=version_no, storage_uri=uri, transform_log=log
    )
    db.add(version)
    await db.flush()

    # 重新校验新版本并刷新数据集展示状态（原文件不变，预览指向最新版本）
    report = validation.validate(new_df, raw_columns=[str(c) for c in new_df.columns])
    dataset.storage_uri = uri
    dataset.preview = parser.preview_json(new_df)
    dataset.column_profile = report.column_profiles
    dataset.status = "FAILED" if report.status == "FAILED" else "VALIDATED"
    if dataset.source_type == "csv":
        dataset.encoding = "utf-8"
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
    await db.commit()
    await db.refresh(version)
    return version


async def _next_version_no(db: AsyncSession, dataset_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(DatasetVersion.version_no), 0)).where(
        DatasetVersion.dataset_id == dataset_id
    )
    return int((await db.execute(stmt)).scalar_one()) + 1


def _write_new_version(
    storage: StorageBackend, dataset: Dataset, version_no: int, df: pd.DataFrame
) -> str:
    safe_name = dataset.name.replace("/", "_").replace("\\", "_")[-120:]
    key = f"datasets/{dataset.project_id}/{dataset.id}/v{version_no}/{safe_name}"
    buf = io.BytesIO()
    if dataset.source_type == "excel":
        df.to_excel(buf, index=False)
    else:
        buf.write(df.to_csv(index=False).encode("utf-8"))
    size = buf.tell()
    buf.seek(0)
    return storage.put(key, buf, size)


async def list_versions(db: AsyncSession, dataset_id: uuid.UUID) -> list[DatasetVersion]:
    stmt = (
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version_no.desc())
    )
    return list((await db.execute(stmt)).scalars().all())
