"""Worker 侧同步 DB 访问（celery 任务为同步函数；api 侧走 app.db 异步）。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
_factory: sessionmaker[Session] | None = None


def get_sync_session_factory() -> sessionmaker[Session]:
    global _engine, _factory
    if _factory is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _factory
