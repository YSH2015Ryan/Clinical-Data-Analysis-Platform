"""数据集服务：上传接收（docs/12 §2.5）+ 落库 + 校验任务入队。

安全纪律：扩展名白名单 + magic bytes 嗅探 + 大小上限（413）；存储 key 服务端生成，
不信任客户端文件名路径。
"""

import hashlib
import io
import uuid
from typing import Any, BinaryIO

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.models.entities import Dataset, DatasetInsight, DatasetVersion, Project, QualityReport
from app.schemas.auth import CurrentUser
from app.services.projects import _decode_cursor, _encode_cursor
from app.services.storage import StorageBackend

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".tsv", ".txt"}
_EXCEL_EXT = {".xlsx", ".xls"}

_ZIP_MAGIC = b"PK\x03\x04"  # xlsx（OOXML zip）
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # xls（OLE2 复合文档）
_SNIFF_BYTES = 8192


def check_extension(filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError(
            code="UNSUPPORTED_FILE_TYPE",
            status=400,
            message="文件类型不在白名单（.csv/.xlsx/.xls/.tsv/.txt）",
            details={"filename": filename},
        )
    return ext


def sniff_magic(head: bytes, ext: str) -> None:
    """magic bytes 嗅探，防扩展名伪装（docs/12 §2.5）。"""
    if ext == ".xlsx":
        if not head.startswith(_ZIP_MAGIC):
            raise _disguised(ext)
    elif ext == ".xls":
        if not (head.startswith(_OLE2_MAGIC) or head.startswith(_ZIP_MAGIC)):
            raise _disguised(ext)
    else:  # 文本类：前 8KB 含 NUL 视为二进制伪装
        if b"\x00" in head:
            raise _disguised(ext)


def _disguised(ext: str) -> AppError:
    return AppError(
        code="UNSUPPORTED_FILE_TYPE",
        status=400,
        message="文件内容与扩展名不符（magic bytes 嗅探未通过）",
        details={"ext": ext},
    )


def storage_key(project_id: uuid.UUID, dataset_id: uuid.UUID, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")[-120:]
    return f"datasets/{project_id}/{dataset_id}/{safe_name}"


async def ingest_upload(
    db: AsyncSession,
    storage: StorageBackend,
    *,
    project_id: uuid.UUID,
    filename: str,
    stream: BinaryIO,
    max_bytes: int,
    declared_size: int | None = None,
) -> Dataset:
    """流式接收上传：校验 → 写存储 → Dataset(status=VALIDATING) + v1 版本落库。

    调用方负责提交事务与入队校验任务。
    """
    ext = check_extension(filename)
    if declared_size is not None and declared_size > max_bytes:
        raise _too_large(max_bytes)

    hasher = hashlib.sha256()
    buf = io.BytesIO()
    size = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise _too_large(max_bytes)
        hasher.update(chunk)
        buf.write(chunk)

    buf.seek(0)
    sniff_magic(buf.read(_SNIFF_BYTES), ext)
    buf.seek(0)

    dataset = Dataset(
        project_id=project_id,
        name=filename,
        source_type="excel" if ext in _EXCEL_EXT else "csv",
        storage_uri="",
        file_hash=hasher.hexdigest(),
        file_size=size,
        status="VALIDATING",
    )
    db.add(dataset)
    await db.flush()

    key = storage_key(project_id, dataset.id, filename)
    uri = storage.put(key, buf, size)
    dataset.storage_uri = uri

    db.add(DatasetVersion(dataset_id=dataset.id, version_no=1, storage_uri=uri))
    return dataset


def _too_large(max_bytes: int) -> AppError:
    return AppError(
        code="FILE_TOO_LARGE",
        status=413,
        message="文件超过大小上限",
        details={"max_mb": max_bytes // (1024 * 1024)},
    )


# ---------- 查询（T2.5：项目级隔离，越权返回 None → api 层 404） ----------


def _owner_filter(user: CurrentUser) -> ColumnElement[bool]:
    """非 admin 强制 owner_id == current_user.id（docs/12 §2.2）。"""
    if user.role == "admin":
        return true()
    return Project.owner_id == user.id


async def get_dataset(db: AsyncSession, user: CurrentUser, dataset_id: uuid.UUID) -> Dataset | None:
    stmt = (
        select(Dataset)
        .join(Project, Dataset.project_id == Project.id)
        .where(
            Dataset.id == dataset_id,
            Dataset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
            _owner_filter(user),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_datasets(
    db: AsyncSession, user: CurrentUser, project_id: uuid.UUID, cursor: str | None, limit: int
) -> tuple[list[Dataset], str | None]:
    offset = _decode_cursor(cursor) if cursor else 0
    stmt = (
        select(Dataset)
        .join(Project, Dataset.project_id == Project.id)
        .where(
            Dataset.project_id == project_id,
            Dataset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
            _owner_filter(user),
        )
        .order_by(Dataset.created_at.desc(), Dataset.id)
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    items, next_cursor = rows[:limit], None
    if len(rows) > limit:
        next_cursor = _encode_cursor(offset + limit)
    return items, next_cursor


async def get_latest_report(db: AsyncSession, dataset_id: uuid.UUID) -> QualityReport | None:
    stmt = (
        select(QualityReport)
        .where(QualityReport.dataset_id == dataset_id)
        .order_by(QualityReport.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_latest_insight(db: AsyncSession, dataset_id: uuid.UUID) -> DatasetInsight | None:
    """最新数据体检（P2-2，docs/08 §3.2 阶段 A 产出）。"""
    stmt = (
        select(DatasetInsight)
        .where(DatasetInsight.dataset_id == dataset_id)
        .order_by(DatasetInsight.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def recommended_preprocess_dsl(
    db: AsyncSession, dataset: Dataset, storage: "StorageBackend"
) -> dict[str, Any]:
    """推荐预处理 DSL（docs/06 §2；P1-2 修复双实现分叉）。

    宽表走毫秒级 profile 版；校验判定为长表（最新质量报告含 RV801）时
    加载 DataFrame 走完整版，以产出 reshape 步骤——profile 不含行级关系，
    无法做长表检测。
    """
    from app.engines import parser
    from app.engines.recommender import recommend_config, recommend_config_from_profile
    from app.services.storage import key_from_uri

    if not dataset.column_profile:
        raise AppError(
            code="VALIDATION_ERROR",
            status=400,
            message="数据集尚未完成验证，请等待验证完成后再生成推荐配置",
        )
    report = await get_latest_report(db, dataset.id)
    is_long = report is not None and any(
        i.get("rule_id") == "RV801" for i in (report.issues or [])
    )
    if not is_long:
        return recommend_config_from_profile(dataset.column_profile)
    raw = storage.get(key_from_uri(dataset.storage_uri))
    parsed = parser.parse(raw, dataset.source_type)
    return recommend_config(parsed.df)
