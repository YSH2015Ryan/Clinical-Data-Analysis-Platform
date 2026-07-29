"""数据集校验任务（docs/05 §2 流水线：解析 → 画像 → 规则 → 报告）。

T2.2：解析 + 预览入库；T2.3：列类型推断；T2.4：18 规则校验 + 质量报告。
幂等纪律：任务可重入，状态以 DB 为准；失败置 FAILED 并记录错误。
"""

import uuid

from sqlalchemy import select

from app.core.logging import get_logger
from app.engines import parser
from app.models.entities import Dataset
from app.services.storage import storage_from_settings
from app.workers.celery_app import celery_app
from app.workers.db import get_sync_session_factory

logger = get_logger(__name__)


@celery_app.task(name="app.workers.dataset_tasks.validate_dataset")
def validate_dataset(dataset_id: str) -> None:
    session_factory = get_sync_session_factory()
    with session_factory() as db:
        dataset = db.execute(
            select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
        ).scalar_one_or_none()
        if dataset is None:
            logger.warning("validate_dataset_not_found", dataset_id=dataset_id)
            return
        try:
            raw = storage_from_settings().get(_storage_key_from_uri(dataset.storage_uri))
            result = parser.parse(raw, dataset.source_type)
            dataset.encoding = result.encoding
            dataset.preview = parser.preview_json(result.df)
            db.commit()
            logger.info(
                "dataset_parsed",
                dataset_id=dataset_id,
                rows=len(result.df),
                cols=len(result.df.columns),
                encoding=result.encoding,
            )
        except Exception as exc:
            dataset.status = "FAILED"
            db.commit()
            logger.error("dataset_parse_failed", dataset_id=dataset_id, error=type(exc).__name__)
            raise


def _storage_key_from_uri(uri: str) -> str:
    """S3 uri (s3://bucket/key) → key；local 模式 uri 即路径，key 取相对部分。"""
    if uri.startswith("s3://"):
        return uri.split("/", 3)[3]
    # local: <root>/<key>，key 以 datasets/ 开头
    idx = uri.find("datasets/")
    return uri[idx:] if idx >= 0 else uri
