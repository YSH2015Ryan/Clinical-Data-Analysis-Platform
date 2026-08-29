"""T8.1 插件管理 API 测试（docs/14 /admin/plugins、/models；docs/15 §1）。

- GET /admin/plugins：仅 admin；先同步注册表，全量可见；
- PATCH /admin/plugins/{key}：仅 admin；禁用后 /models 过滤、create_run PLUGIN_UNAVAILABLE；
- 未知 key 404；非 admin 403；已完成的运行不受禁用影响（model_params 已快照）。
"""

import pytest
from app.core.security import hash_password
from app.models.entities import User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_analysis_api import _auth, _body
from tests.test_analysis_api import researcher as _researcher_impl
from tests.test_analysis_api import version as _version_impl
from tests.test_analysis_api import worker_sync_db as _ws_impl

# 共享 fixture 再导出（pytest 按模块属性名发现）
researcher = _researcher_impl
version = _version_impl
worker_sync_db = _ws_impl


@pytest.fixture()
async def admin(db_session: AsyncSession) -> User:
    user = User(
        email="admin@example.com",
        password_hash=hash_password("admin-pass"),
        role="admin",
        display_name="Admin",
    )
    db_session.add(user)
    await db_session.commit()
    return user


class TestListAdminPlugins:
    async def test_admin_lists_all(self, client: AsyncClient, admin: User) -> None:
        resp = await client.get("/api/v1/admin/plugins", headers=_auth(admin))
        assert resp.status_code == 200
        keys = {p["key"] for p in resp.json()}
        assert {"dummy", "logreg"} <= keys
        dummy = next(p for p in resp.json() if p["key"] == "dummy")
        assert dummy["enabled"] is True
        assert "classification" in dummy["task_types"]

    async def test_non_admin_403(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get("/api/v1/admin/plugins", headers=_auth(researcher))
        assert resp.status_code == 403


class TestModelTiering:
    """T6.12 模型分层套餐：/models 返回 tier/role，标准套餐在前（docs/14 变更记录 2026-08-27）。"""

    async def test_models_carry_tier_and_role(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get(
            "/api/v1/models", params={"task_type": "classification"}, headers=_auth(researcher)
        )
        assert resp.status_code == 200
        items = resp.json()
        by_key = {p["key"]: p for p in items}
        assert by_key["logreg"]["tier"] == "standard"
        assert by_key["logreg"]["role"]  # 角色标注非空
        assert by_key["catboost"]["tier"] == "advanced"
        assert by_key["catboost"]["role"] is None

    async def test_standard_first_ordering(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get(
            "/api/v1/models", params={"task_type": "survival"}, headers=_auth(researcher)
        )
        tiers = [p["tier"] for p in resp.json()]
        assert tiers == sorted(tiers, key=lambda t: t != "standard")
        assert {p["key"] for p in resp.json() if p["tier"] == "standard"} == {
            "coxph",
            "rsf",
            "gbs",
        }

    async def test_tier_depends_on_queried_task(
        self, client: AsyncClient, researcher: User
    ) -> None:
        """gam：回归标准套餐 / 分类高级选项（同一插件按任务分层）。"""
        reg = await client.get(
            "/api/v1/models", params={"task_type": "regression"}, headers=_auth(researcher)
        )
        clf = await client.get(
            "/api/v1/models", params={"task_type": "classification"}, headers=_auth(researcher)
        )
        gam_reg = next(p for p in reg.json() if p["key"] == "gam")
        gam_clf = next(p for p in clf.json() if p["key"] == "gam")
        assert gam_reg["tier"] == "standard"
        assert gam_clf["tier"] == "advanced"

    async def test_admin_view_marks_any_standard(self, client: AsyncClient, admin: User) -> None:
        resp = await client.get("/api/v1/admin/plugins", headers=_auth(admin))
        by_key = {p["key"]: p for p in resp.json()}
        assert by_key["coxph"]["tier"] == "standard"
        assert by_key["km"]["tier"] == "advanced"


class TestUpdatePlugin:
    async def test_disable_then_models_filtered(
        self, client: AsyncClient, admin: User, researcher: User
    ) -> None:
        resp = await client.patch(
            "/api/v1/admin/plugins/dummy",
            json={"enabled": False},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        models = await client.get(
            "/api/v1/models", params={"task_type": "classification"}, headers=_auth(researcher)
        )
        assert models.status_code == 200
        keys = {p["key"] for p in models.json()}
        assert "dummy" not in keys
        assert "logreg" in keys

    async def test_disable_blocks_create_run(
        self, client: AsyncClient, admin: User, researcher: User, version
    ) -> None:
        resp = await client.patch(
            "/api/v1/admin/plugins/dummy",
            json={"enabled": False},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        run = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert run.status_code == 400
        assert run.json()["code"] == "PLUGIN_UNAVAILABLE"

    async def test_update_default_params(self, client: AsyncClient, admin: User) -> None:
        resp = await client.patch(
            "/api/v1/admin/plugins/logreg",
            json={"default_params": {"C": 2.0}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["key"] == "logreg"
        assert resp.json()["capability"]["default_params"] == {"C": 2.0}

    async def test_unknown_key_404(self, client: AsyncClient, admin: User) -> None:
        resp = await client.patch(
            "/api/v1/admin/plugins/no_such",
            json={"enabled": False},
            headers=_auth(admin),
        )
        assert resp.status_code == 404

    async def test_non_admin_403(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.patch(
            "/api/v1/admin/plugins/dummy",
            json={"enabled": False},
            headers=_auth(researcher),
        )
        assert resp.status_code == 403


@pytest.mark.usefixtures("worker_sync_db")
class TestHistoryRunUnaffected:
    async def test_completed_run_survives_disable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin: User,
        researcher: User,
        version,
    ) -> None:
        """禁用插件不影响已完成运行（docs/15 §1：运行时 model_params 已快照）。"""
        run = await client.post(
            "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
        )
        assert run.status_code == 202
        run_id = run.json()["id"]
        db_session.expunge_all()

        await client.patch(
            "/api/v1/admin/plugins/dummy", json={"enabled": False}, headers=_auth(admin)
        )

        detail = await client.get(f"/api/v1/analysis-runs/{run_id}", headers=_auth(researcher))
        assert detail.status_code == 200
        assert detail.json()["status"] == "COMPLETED"
