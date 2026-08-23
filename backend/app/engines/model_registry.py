"""模型插件注册表：ModelAdapter 协议 + entry_points 扫描 + 注册校验（docs/07 §2、docs/15 §2）。

- 内置模型即插件（app.plugins.builtin），核心不特殊对待内置（docs/15 §1 验收点）；
- 加载：importlib.metadata.entry_points(group="cdap.models") 扫描；
- 注册校验（失败拒绝）：key 全局唯一且匹配 ``^[a-z][a-z0-9_]{1,40}$``、
  协议方法齐备（inspect.signature）、task_types 合法子集；
- DB 同步在 services/plugins.py（engines 禁止 import sqlalchemy）。

分层纪律：engines 只依赖标准库/数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

import inspect
import re
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)

ENTRY_POINT_GROUP = "cdap.models"
VALID_TASK_TYPES = frozenset({"survival", "classification", "regression", "time_series"})
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

# 协议方法的必填参数（docs/07 §2；inspect.signature 校验）
_REQUIRED_METHODS: dict[str, list[str]] = {
    "fit": ["X", "y", "params"],
    "evaluate": ["X_val", "y_val"],
    "explain": ["X_val"],
    "predict_artifacts": ["X_val", "y_val"],
}
_REQUIRED_ATTRS = ("key", "name", "version", "task_types", "capabilities", "default_params")


class ModelAdapter(Protocol):
    """模型适配器协议（docs/07 §2）；满足协议的类经 entry_points 注册即可被发现。"""

    key: str
    name: str
    version: str
    task_types: list[str]
    capabilities: dict[str, Any]
    default_params: dict[str, Any]

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None: ...

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]: ...

    def explain(self, X_val: Any) -> dict[str, Any] | None: ...

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]: ...


def validate_adapter(adapter: Any) -> list[str]:
    """注册校验（docs/15 §2）；返回错误列表，空列表 = 合法。"""
    errors: list[str] = []
    for attr in _REQUIRED_ATTRS:
        if not hasattr(adapter, attr):
            errors.append(f"缺少协议属性 {attr}")
    if errors:
        return errors

    key = getattr(adapter, "key", "")
    if not isinstance(key, str) or not KEY_RE.match(key):
        errors.append(f"key {key!r} 非法：须匹配 ^[a-z][a-z0-9_]{{1,40}}$")

    task_types = getattr(adapter, "task_types", [])
    if (
        not isinstance(task_types, list)
        or not task_types
        or not set(task_types) <= VALID_TASK_TYPES
    ):
        errors.append(f"task_types {task_types!r} 非法：须为 {sorted(VALID_TASK_TYPES)} 的非空子集")

    for method, params in _REQUIRED_METHODS.items():
        fn = getattr(adapter, method, None)
        if not callable(fn):
            errors.append(f"缺少协议方法 {method}")
            continue
        sig_params = list(inspect.signature(fn).parameters)
        if len(sig_params) < len(params):
            errors.append(f"方法 {method} 签名非法：须接受 {params}（当前 {sig_params}）")
    return errors


@dataclass
class RegisteredAdapter:
    adapter: Any
    entry_point: str


class ModelRegistry:
    """entry_points 扫描 + 注册表；非法/重 key 插件拒绝加载（日志告警）。"""

    def __init__(self) -> None:
        self._adapters: dict[str, RegisteredAdapter] = {}

    def register(self, adapter: Any, entry_point: str) -> None:
        errors = validate_adapter(adapter)
        if errors:
            raise ValueError(f"非法插件 {getattr(adapter, 'key', '?')!r}：{'；'.join(errors)}")
        if adapter.key in self._adapters:
            existing = self._adapters[adapter.key].entry_point
            raise ValueError(f"重复 key {adapter.key!r}：已被 {existing} 注册")
        self._adapters[adapter.key] = RegisteredAdapter(adapter=adapter, entry_point=entry_point)

    def load(self, group: str = ENTRY_POINT_GROUP) -> None:
        """扫描 entry_points 注册全部插件；单个加载/校验失败仅告警跳过。"""
        for ep in importlib_metadata.entry_points(group=group):
            try:
                adapter_cls = ep.load()
                self.register(adapter_cls(), entry_point=ep.value)
            except Exception as exc:
                logger.warning("model_plugin_rejected", entry_point=ep.value, error=str(exc))

    def get(self, key: str) -> Any | None:
        registered = self._adapters.get(key)
        return registered.adapter if registered else None

    def entry_point_of(self, key: str) -> str | None:
        registered = self._adapters.get(key)
        return registered.entry_point if registered else None

    def for_task(self, task_type: str) -> list[Any]:
        return [r.adapter for r in self._adapters.values() if task_type in r.adapter.task_types]

    def all(self) -> list[RegisteredAdapter]:
        return list(self._adapters.values())
