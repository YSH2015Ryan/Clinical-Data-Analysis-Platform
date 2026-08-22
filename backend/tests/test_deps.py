"""T1.1/T1.2 依赖层测试：get_current_user + require_role（docs/12 §2.2）。"""

import uuid

import pytest
from app.api.deps import get_current_user, require_role
from app.core.errors import AppError
from app.core.security import create_token, hash_password
from app.models.entities import User
from app.schemas.auth import CurrentUser
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


@pytest.fixture()
async def viewer_user(db_session: AsyncSession) -> User:
    user = User(
        email="viewer@example.com",
        password_hash=hash_password("viewer-pass"),
        role="viewer",
        display_name="Viewer",
    )
    db_session.add(user)
    await db_session.commit()
    return user


def _cred(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _request(claims: dict[str, object] | None = None) -> Request:
    scope: dict[str, object] = {"type": "http", "headers": []}
    if claims is not None:
        scope["cdap.access_claims"] = claims
    return Request(scope)  # type: ignore[arg-type]


class TestGetCurrentUser:
    async def test_no_credentials_401(self, db_session: AsyncSession) -> None:
        with pytest.raises(AppError) as exc_info:
            await get_current_user(request=_request(), cred=None, cdap_access=None, db=db_session)
        assert exc_info.value.code == "AUTH_FAILED"
        assert exc_info.value.status == 401

    async def test_garbage_token_401(self, db_session: AsyncSession) -> None:
        with pytest.raises(AppError) as exc_info:
            await get_current_user(
                request=_request(), cred=_cred("garbage"), cdap_access=None, db=db_session
            )
        assert exc_info.value.code == "AUTH_FAILED"

    async def test_valid_token_returns_principal(
        self, db_session: AsyncSession, viewer_user: User
    ) -> None:
        token = create_token(str(viewer_user.id), "viewer", "access")
        principal = await get_current_user(
            request=_request(), cred=_cred(token), cdap_access=None, db=db_session
        )
        assert principal.id == viewer_user.id
        assert principal.role == "viewer"

    async def test_unknown_user_401(self, db_session: AsyncSession) -> None:
        token = create_token(str(uuid.uuid4()), "viewer", "access")
        with pytest.raises(AppError) as exc_info:
            await get_current_user(
                request=_request(), cred=_cred(token), cdap_access=None, db=db_session
            )
        assert exc_info.value.code == "AUTH_FAILED"


class TestRequireRole:
    async def test_viewer_blocked_from_researcher_route(self) -> None:
        checker = require_role("researcher")
        viewer = CurrentUser(id=uuid.uuid4(), email="v@x.com", role="viewer")
        with pytest.raises(AppError) as exc_info:
            await checker(viewer)
        assert exc_info.value.code == "FORBIDDEN"
        assert exc_info.value.status == 403

    async def test_researcher_allowed(self) -> None:
        checker = require_role("researcher")
        researcher = CurrentUser(id=uuid.uuid4(), email="r@x.com", role="researcher")
        assert await checker(researcher) is researcher

    async def test_admin_bypasses(self) -> None:
        checker = require_role("researcher")
        admin = CurrentUser(id=uuid.uuid4(), email="a@x.com", role="admin")
        assert await checker(admin) is admin
