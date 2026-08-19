"""FastAPI 入口（docs/12）。健康检查契约见 docs/14（/healthz /readyz）。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import admin as admin_api
from app.api.v1 import analysis as analysis_api
from app.api.v1 import auth as auth_api
from app.api.v1 import datasets as datasets_api
from app.api.v1 import projects as projects_api
from app.api.v1 import reports as reports_api
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db import dispose_engine, get_engine, get_session_factory
from app.engines.model_registry import ModelRegistry
from app.services.plugins import sync_plugins_to_db
from app.services.storage import storage_from_settings

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    # 数据库迁移完成后立即同步插件，避免新部署的分析向导拿到空模型列表。
    try:
        registry = ModelRegistry()
        registry.load()
        async with get_session_factory()() as db:
            await sync_plugins_to_db(db, registry)
            await db.commit()
    except Exception:
        if settings.environment == "prod":
            raise
        logger.warning("plugin_sync_deferred", exc_info=True)
    logger.info("app_started", app=settings.app_name)
    yield
    await dispose_engine()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="CDAP API", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)

    # 所有端点挂在 /api/v1 下（docs/14 Base URL 约定）
    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth_api.router)
    v1.include_router(projects_api.router)
    v1.include_router(datasets_api.router)
    v1.include_router(datasets_api.dataset_router)
    v1.include_router(datasets_api.preparation_router)
    v1.include_router(analysis_api.router)
    v1.include_router(reports_api.router)
    v1.include_router(admin_api.router)

    @v1.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @v1.get("/readyz")
    async def readyz() -> JSONResponse:
        components: dict[str, str] = {}
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            components["database"] = "ok"
        except Exception as exc:
            components["database"] = f"error: {type(exc).__name__}"
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(get_settings().redis_url)  # type: ignore[no-untyped-call]
            await client.ping()
            await client.aclose()
            components["redis"] = "ok"
        except Exception as exc:
            components["redis"] = f"error: {type(exc).__name__}"
        try:
            components["storage"] = (
                "ok" if storage_from_settings().healthcheck() else "error: unavailable"
            )
        except Exception as exc:
            components["storage"] = f"error: {type(exc).__name__}"

        ok = all(v == "ok" for v in components.values())
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ok" if ok else "not_ready", "components": components},
        )

    app.include_router(v1)
    return app


app = create_app()
