import os

# 测试环境默认：本地存储 + 内存级配置，不触真实基础设施
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_STORAGE_PATH", "./.test_storage")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://cdap:cdap@localhost:5432/cdap")
# 集成测试专用库（与开发库隔离；CI 由 service 容器提供）
os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+psycopg://cdap:cdap@localhost:5432/cdap_test"
)

from collections.abc import AsyncIterator

import pytest
from app.main import create_app
from app.models.base import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    """集成测试会话：每个测试用例重建 schema（testcontainers/CI service/本地 compose 均可）。"""
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
async def client(db_session: AsyncSession):
    """FastAPI 测试客户端：get_db 覆盖为测试会话。"""
    from collections.abc import AsyncIterator as _AI

    from app.db import get_db
    from httpx import ASGITransport, AsyncClient

    app = create_app()

    async def _override() -> _AI[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
