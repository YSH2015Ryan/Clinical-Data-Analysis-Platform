"""Celery 应用（docs/12 §3）。

worker 只做参数解包 → 调 engines/services → 落库，不含业务规则（分层纪律）。
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "cdap",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.dataset_tasks"],  # 任务模块注册（worker 启动时 import）
)

celery_app.conf.update(
    task_acks_late=True,  # 长任务宕机可重投（docs/20 R1）
    worker_prefetch_multiplier=1,  # 公平调度
    task_time_limit=settings.model_timeout_s,
    task_default_queue="default",
    task_routes={
        "app.workers.model_tasks.*": {"queue": "model"},
        "app.workers.report_tasks.*": {"queue": "report"},
    },
    result_expires=86400,
)
