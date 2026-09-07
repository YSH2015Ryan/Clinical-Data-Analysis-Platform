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
    include=[
        "app.workers.dataset_tasks",
        "app.workers.insight_tasks",
        "app.workers.preparation_tasks",
        "app.workers.analysis_tasks",
        "app.workers.report_tasks",
        "app.workers.project_tasks",
        # 注意：远端 hotfix 曾 include "app.workers.quickfix_tasks"，但该模块从未提交，
        # include 缺失模块会导致 worker 启动即 ModuleNotFoundError，故剔除。
    ],  # 任务模块注册
)

celery_app.conf.update(
    task_acks_late=True,  # 长任务宕机可重投（docs/20 R1）
    worker_prefetch_multiplier=1,  # 公平调度
    # Phase 6 T6.5: 全局超时设置为 70 分钟（与 config.model_timeout_s 一致）
    task_time_limit=settings.model_timeout_s,
    task_soft_time_limit=settings.model_timeout_s - 60,  # 软超时比硬超时早 60s
    task_default_queue="default",
    task_routes={
        "app.workers.analysis_tasks.run_model": {"queue": "model"},
        "app.workers.model_tasks.*": {"queue": "model"},
        "app.workers.report_tasks.*": {"queue": "report"},
    },
    # Phase 6 T6.5: preprocess 任务保持 10 分钟超时（已足够）
    task_annotations={
        "app.workers.analysis_tasks.preprocess_run": {
            "time_limit": 660,
            "soft_time_limit": 600,
        },
    },
    result_expires=86400,
    beat_schedule={
        # docs/12 §3：janitor 巡检超时 RUNNING → FAILED（kill -9 恢复）
        "janitor-sweep": {
            "task": "app.workers.analysis_tasks.janitor_sweep",
            "schedule": 300.0,
        },
    },
)
