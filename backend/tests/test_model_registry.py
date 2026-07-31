"""T5.1 ModelAdapter 协议 + entry_points 注册表 + DB 同步（docs/07 §2、docs/15 §1-2）。

DoD：dummy 插件零改动注册（真实 entry_points 扫描）；非法插件拒绝加载
（key 非法/缺方法/重 key/非法 task_types）；DB 同步保留 enabled 状态。
"""

from typing import Any, ClassVar

import pytest
from app.engines.model_registry import (
    ModelRegistry,
    validate_adapter,
)
from app.models.entities import ModelPlugin
from app.services.plugins import sync_plugins_to_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class GoodAdapter:
    key = "good"
    name = "Good Model"
    version = "1.0.0"
    task_types: ClassVar[list[str]] = ["classification"]
    capabilities: ClassVar[dict[str, Any]] = {"shap": False}
    default_params: ClassVar[dict[str, Any]] = {"alpha": 1.0}

    def fit(self, X, y, params: dict) -> None: ...

    def evaluate(self, X_val, y_val) -> dict:
        return {"auc": 0.5}

    def explain(self, X_val) -> dict | None:
        return None

    def predict_artifacts(self, X_val, y_val) -> dict:
        return {}


class TestValidateAdapter:
    def test_valid_passes(self) -> None:
        assert validate_adapter(GoodAdapter()) == []

    def test_bad_key_format(self) -> None:
        bad = GoodAdapter()
        bad.key = "Bad Key!"
        errors = validate_adapter(bad)
        assert any("key" in e for e in errors)

    def test_bad_task_types(self) -> None:
        bad = GoodAdapter()
        bad.task_types = ["magic"]
        errors = validate_adapter(bad)
        assert any("task_types" in e for e in errors)

    def test_missing_method(self) -> None:
        class Incomplete:
            key = "incomplete"
            name = "x"
            version = "1.0.0"
            task_types: ClassVar[list[str]] = ["classification"]
            capabilities: ClassVar[dict[str, Any]] = {}
            default_params: ClassVar[dict[str, Any]] = {}

        errors = validate_adapter(Incomplete())
        assert any("fit" in e for e in errors)
        assert any("evaluate" in e for e in errors)


class TestRegistry:
    def test_dummy_plugin_registered_via_entry_points(self) -> None:
        """真实扫描已安装包的 entry_points：dummy 插件零改动注册（DoD 核心）。"""
        registry = ModelRegistry()
        registry.load()
        dummy = registry.get("dummy")
        assert dummy is not None
        assert dummy.name
        assert dummy.task_types

    def test_register_manual_and_for_task(self) -> None:
        registry = ModelRegistry()
        registry.register(GoodAdapter(), entry_point="tests:GoodAdapter")
        assert registry.get("good") is not None
        assert [a.key for a in registry.for_task("classification")] == ["good"]
        assert registry.for_task("survival") == []

    def test_duplicate_key_rejected(self) -> None:
        registry = ModelRegistry()
        registry.register(GoodAdapter(), entry_point="tests:GoodAdapter")
        other = GoodAdapter()
        with pytest.raises(ValueError, match="重复"):
            registry.register(other, entry_point="tests:Other")

    def test_invalid_adapter_rejected(self) -> None:
        registry = ModelRegistry()
        bad = GoodAdapter()
        bad.key = "!!bad"
        with pytest.raises(ValueError, match="非法"):
            registry.register(bad, entry_point="tests:Bad")


class TestDbSync:
    async def test_insert_new_and_preserve_enabled(self, db_session: AsyncSession) -> None:
        registry = ModelRegistry()
        registry.register(GoodAdapter(), entry_point="tests:GoodAdapter")

        await sync_plugins_to_db(db_session, registry)
        await db_session.commit()
        row = (
            await db_session.execute(select(ModelPlugin).where(ModelPlugin.key == "good"))
        ).scalar_one()
        assert row.enabled is True
        assert row.version == "1.0.0"
        assert row.entry_point == "tests:GoodAdapter"
        assert row.task_types == ["classification"]

        # 禁用后重新同步：enabled 以 DB 为准不被覆盖，版本字段更新
        row.enabled = False
        await db_session.commit()
        GoodAdapter.version = "1.1.0"
        registry2 = ModelRegistry()
        registry2.register(GoodAdapter(), entry_point="tests:GoodAdapter")
        await sync_plugins_to_db(db_session, registry2)
        await db_session.commit()
        await db_session.refresh(row)
        assert row.enabled is False
        assert row.version == "1.1.0"
