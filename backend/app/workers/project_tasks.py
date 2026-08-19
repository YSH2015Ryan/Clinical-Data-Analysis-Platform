"""项目删除后的对象存储补偿清理。"""

from app.core.logging import get_logger
from app.services.storage import storage_from_settings
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="app.workers.project_tasks.purge_project_storage",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def purge_project_storage(keys: list[str]) -> dict[str, int]:
    storage = storage_from_settings()
    removed = 0
    failed = 0
    for key in keys:
        try:
            if key.endswith("/"):
                storage.delete_prefix(key)
            else:
                storage.delete(key)
            removed += 1
        except Exception as exc:
            failed += 1
            logger.warning("project_storage_cleanup_failed", key=key, error=str(exc))
    if failed:
        raise RuntimeError(f"对象存储清理失败 {failed} 项，已重试")
    return {"removed": removed, "failed": failed}
