"""数据集校验任务（T2.1 入队占位；T2.2–T2.4 填充解析/推断/规则引擎）。

幂等纪律（docs/Appendix C §6）：任务可重入，以数据集当前状态为准。
"""

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="app.workers.dataset_tasks.validate_dataset")
def validate_dataset(dataset_id: str) -> None:
    # T2.2–T2.4：编码/分隔符嗅探 → 列类型推断 → 18 规则校验 → 质量报告落库
    logger.info("validate_dataset_received", dataset_id=dataset_id)
