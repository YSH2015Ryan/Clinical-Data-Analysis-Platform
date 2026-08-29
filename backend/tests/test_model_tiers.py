"""T6.12 模型分层套餐单测（tasks/phase6 T6.12）。

- 每任务标准套餐 3–5 个，构成含基线+强模型+可解释模型（角色标注齐备）；
- 套餐内 key 必须真实存在于内置插件且支持对应任务类型（防虚构模型）；
- tier_of/role_of 行为：套餐内 standard，其余 advanced；跨任务插件按查询任务判定。
"""

from app.engines.model_registry import KEY_RE, ModelRegistry
from app.engines.model_tiers import (
    STANDARD_PACKAGES,
    role_of,
    tier_of,
)
from app.plugins import builtin  # noqa: F401  # 确保 entry_points 已注册可发现


def _registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.load()
    return registry


class TestPackageShape:
    def test_three_task_types_have_packages(self) -> None:
        assert set(STANDARD_PACKAGES) == {"classification", "regression", "survival"}

    def test_package_size_3_to_5(self) -> None:
        for task, keys in STANDARD_PACKAGES.items():
            assert 3 <= len(keys) <= 5, f"{task} 标准套餐应为 3–5 个，实际 {len(keys)}"

    def test_package_keys_unique_and_wellformed(self) -> None:
        for keys in STANDARD_PACKAGES.values():
            assert len(set(keys)) == len(keys)
            for key in keys:
                assert KEY_RE.match(key), f"非法模型 key: {key}"

    def test_every_standard_model_has_role(self) -> None:
        for keys in STANDARD_PACKAGES.values():
            for key in keys:
                assert role_of(key), f"标准套餐模型 {key} 缺角色标注"


class TestPackageRealModels:
    """套餐 key 必须真实注册且支持对应任务（红线8：不推荐不存在的模型）。"""

    def test_package_models_registered_and_support_task(self) -> None:
        registry = _registry()
        for task, keys in STANDARD_PACKAGES.items():
            available = {a.key for a in registry.for_task(task)}
            for key in keys:
                assert key in available, f"{task} 套餐模型 {key} 未注册或不支持该任务"

    def test_package_composition_baseline_strong_interpretable(self) -> None:
        """每任务套餐角色覆盖：基线 + 强模型 + 可解释（角色文案含关键词核对）。"""
        for task, keys in STANDARD_PACKAGES.items():
            roles = [role_of(k) or "" for k in keys]
            joined = " ".join(roles)
            assert "基线" in joined, f"{task} 缺基线模型"
            assert "强模型" in joined, f"{task} 缺强模型"
            assert "可解释" in joined, f"{task} 缺可解释模型"


class TestTierOf:
    def test_standard_models(self) -> None:
        assert tier_of("classification", "logreg") == "standard"
        assert tier_of("regression", "gam") == "standard"
        assert tier_of("survival", "coxph") == "standard"

    def test_advanced_models(self) -> None:
        assert tier_of("classification", "catboost") == "advanced"
        assert tier_of("classification", "dummy") == "advanced"
        assert tier_of("survival", "deepsurv") == "advanced"
        assert tier_of("regression", "poisson") == "advanced"

    def test_cross_task_plugin_depends_on_queried_task(self) -> None:
        """gam 同时支持回归与分类：回归套餐内 → standard；分类套餐外 → advanced。"""
        assert tier_of("regression", "gam") == "standard"
        assert tier_of("classification", "gam") == "advanced"

    def test_unknown_task_type_all_advanced(self) -> None:
        assert tier_of("time_series", "logreg") == "advanced"

    def test_role_of_advanced_is_none(self) -> None:
        assert role_of("catboost") is None
