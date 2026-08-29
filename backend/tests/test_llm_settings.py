"""T6.6 LLM 设置（roadmap T6.6；docs/14 /admin/settings/llm*）。

- 服务层：Fernet 加密往返、env 默认 + DB 覆盖合并、key 掩码、审计不含值；
- 隐私守卫：聚合 facts 放行，行级数据（禁用键/超长集合/超大体积）拦截；
- API：仅 admin；PUT 后 GET 生效且无明文 key；test 端点真实反映可用性（mock 传输层）；
- 云端总闸：LLM_CLOUD_ENABLED=false 时云端路径拒绝。
"""

import json
from typing import Any

import pytest
from app.core.security import hash_password
from app.models.entities import AdminSetting, AuditLog, User
from app.services import settings as settings_service
from app.services.llm_privacy import CloudPayloadViolation, assert_cloud_payload_safe
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_analysis_api import _auth
from tests.test_analysis_api import researcher as _researcher_impl

researcher = _researcher_impl


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


class TestSettingsService:
    async def test_roundtrip_non_secret(self, db_session: AsyncSession) -> None:
        await settings_service.set_value(db_session, "llm.model_choice", "local")
        assert await settings_service.get_value(db_session, "llm.model_choice") == "local"

    async def test_secret_encrypted_at_rest(self, db_session: AsyncSession) -> None:
        await settings_service.set_value(
            db_session, "llm.openai_api_key", "sk-test-1234567890", secret=True
        )
        row = await db_session.get(AdminSetting, "llm.openai_api_key")
        assert row is not None and row.is_secret is True
        assert "sk-test" not in row.value  # 落库为密文
        assert (
            await settings_service.get_value(db_session, "llm.openai_api_key")
            == "sk-test-1234567890"
        )

    async def test_mask_secret(self) -> None:
        assert settings_service.mask_secret("sk-abcdef123456") == "sk-****3456"
        assert settings_service.mask_secret("short") == "****"

    async def test_env_defaults_when_db_empty(self, db_session: AsyncSession) -> None:
        cfg = await settings_service.get_llm_config(db_session)
        assert cfg.model_choice == "auto"
        assert cfg.temperature == 0.3
        assert cfg.ollama_model  # env 默认
        assert cfg.openai_api_key is None
        assert cfg.feature_switches == {
            "research_profile": "off",
            "report_interpretation": "off",
            "validation_explain": "off",
            "iteration": "off",  # T6.13
        }

    async def test_partial_update_and_key_clear(self, db_session: AsyncSession) -> None:
        cfg = await settings_service.update_llm_config(
            db_session, model_choice="local", temperature=0.7
        )
        assert cfg.model_choice == "local" and cfg.temperature == 0.7
        # 再更新其他字段不影响已存值
        cfg = await settings_service.update_llm_config(db_session, ollama_model="qwen2.5:3b")
        assert cfg.model_choice == "local" and cfg.ollama_model == "qwen2.5:3b"
        # key 设置后清除
        cfg = await settings_service.update_llm_config(db_session, openai_api_key="sk-x9y8z7w6v5")
        assert cfg.openai_api_key == "sk-x9y8z7w6v5"
        cfg = await settings_service.update_llm_config(db_session, openai_api_key="")
        assert cfg.openai_api_key is None

    async def test_feature_switches_merge(self, db_session: AsyncSession) -> None:
        cfg = await settings_service.update_llm_config(
            db_session, feature_switches={"research_profile": "local_first"}
        )
        assert cfg.feature_switches["research_profile"] == "local_first"
        assert cfg.feature_switches["report_interpretation"] == "off"  # 其余保持默认


class TestCloudPayloadGuard:
    def test_aggregate_facts_pass(self) -> None:
        facts: dict[str, Any] = {
            "auc": {"mean": 0.87, "std": 0.03, "folds": [0.85, 0.88, 0.89]},
            "comparison": {"t": 4.23, "p": 0.002, "cohens_d": 1.23},
            "top_features": [{"name": "age", "importance": 0.4}],
        }
        assert_cloud_payload_safe(facts)  # 不抛异常即放行

    def test_forbidden_key_rejected(self) -> None:
        with pytest.raises(CloudPayloadViolation, match="禁用键"):
            assert_cloud_payload_safe({"metrics": {"auc": 0.9}, "rows": [1, 2, 3]})

    def test_long_collection_rejected(self) -> None:
        with pytest.raises(CloudPayloadViolation, match="疑似行级数据"):
            assert_cloud_payload_safe({"values": list(range(500))})

    def test_oversize_rejected(self) -> None:
        big = {"note": "x" * 9000}
        with pytest.raises(CloudPayloadViolation, match="体积"):
            assert_cloud_payload_safe(big)


class TestLlmSettingsApi:
    async def test_get_requires_admin(self, client: AsyncClient, researcher: User) -> None:
        resp = await client.get("/api/v1/admin/settings/llm", headers=_auth(researcher))
        assert resp.status_code == 403

    async def test_get_defaults(self, client: AsyncClient, admin: User) -> None:
        resp = await client.get("/api/v1/admin/settings/llm", headers=_auth(admin))
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["model_choice"] == "auto"
        assert body["config"]["cloud_has_key"] is False
        assert body["config"]["cloud_key_preview"] == ""
        assert set(body["status"]) == {"local", "cloud", "default_choice"}

    async def test_put_then_get_no_plaintext_key(
        self, client: AsyncClient, db_session: AsyncSession, admin: User
    ) -> None:
        resp = await client.put(
            "/api/v1/admin/settings/llm",
            json={
                "model_choice": "local",
                "temperature": 0.5,
                "openai_api_key": "sk-live-abcdef123456",
                "feature_switches": {
                    "research_profile": "local_first",
                    "report_interpretation": "off",
                    "validation_explain": "local",
                },
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["model_choice"] == "local"
        assert body["config"]["cloud_has_key"] is True
        assert body["config"]["cloud_key_preview"] == "sk-****3456"
        assert "sk-live-abcdef123456" not in json.dumps(body)  # 红线：无明文

        again = await client.get("/api/v1/admin/settings/llm", headers=_auth(admin))
        assert again.json()["config"]["feature_switches"]["research_profile"] == "local_first"
        assert "sk-live-abcdef123456" not in json.dumps(again.json())

        # 审计只记键名，不记值
        logs = (
            (
                await db_session.execute(
                    select(AuditLog).where(AuditLog.action == "admin.llm_settings_update")
                )
            )
            .scalars()
            .all()
        )
        assert logs, "审计缺失"
        assert "sk-live" not in json.dumps(logs[-1].detail)

    async def test_put_validates_temperature(self, client: AsyncClient, admin: User) -> None:
        resp = await client.put(
            "/api/v1/admin/settings/llm",
            json={"temperature": 1.5},
            headers=_auth(admin),
        )
        assert resp.status_code == 400

    async def test_ollama_models_proxy(
        self, client: AsyncClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api.v1 import settings as settings_api

        class _FakeResp:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"models": [{"name": "qwen2.5:7b"}, {"name": "qwen2.5:3b"}]}

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

            async def get(self, url: str) -> _FakeResp:
                return _FakeResp()

        monkeypatch.setattr(settings_api.httpx, "AsyncClient", _FakeClient)
        resp = await client.get("/api/v1/admin/settings/llm/ollama-models", headers=_auth(admin))
        assert resp.status_code == 200
        assert resp.json() == {"available": True, "models": ["qwen2.5:7b", "qwen2.5:3b"]}

    async def test_test_endpoint_local_success(
        self, client: AsyncClient, admin: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api.v1 import settings as settings_api

        class _FakeResp:
            status_code = 200

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

            async def post(self, url: str, json: dict[str, Any]) -> _FakeResp:
                return _FakeResp()

        monkeypatch.setattr(settings_api.httpx, "AsyncClient", _FakeClient)
        resp = await client.post(
            "/api/v1/admin/settings/llm/test",
            json={"provider": "local"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and body["provider"] == "local"
        assert body["latency_ms"] >= 0

    async def test_test_endpoint_cloud_disabled_by_deployment(
        self, client: AsyncClient, admin: User
    ) -> None:
        # 测试环境 llm_cloud_enabled 默认 false（部署层总闸）
        resp = await client.post(
            "/api/v1/admin/settings/llm/test",
            json={"provider": "cloud"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "禁用" in body["detail"]


class TestCloudGate:
    def test_cloud_disabled_rejects_generate(self) -> None:
        from app.services.llm import LLMService

        service = LLMService(cloud_enabled=False, openai_api_key=None)
        with pytest.raises(RuntimeError, match="部署层禁用"):
            service.generate_interpretation({}, "performance", model_choice="cloud")

    def test_cloud_path_enforces_privacy_guard(self) -> None:
        from app.services.llm import LLMService

        service = LLMService(cloud_enabled=True, openai_api_key=None)
        # 行级数据在 provider 未配置错误之前先被守卫拦截
        with pytest.raises(CloudPayloadViolation):
            service.generate_interpretation(
                {"rows": list(range(1000))}, "performance", model_choice="cloud"
            )
