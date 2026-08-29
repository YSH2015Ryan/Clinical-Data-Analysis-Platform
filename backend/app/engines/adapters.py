"""内置模型插件公共基类（docs/07 §2 协议见 engines.model_registry.ModelAdapter）。

仅作名义基类：协议属性/方法由各插件自行声明，注册校验走 validate_adapter；
 engines 分层纪律不变——本模块不依赖 fastapi/celery/sqlalchemy。
"""

from typing import Any, ClassVar


class BaseModelAdapter:
    """模型适配器名义基类：子类须满足 ModelAdapter 协议（注册时强制校验）。"""

    key: ClassVar[str]
    name: ClassVar[str]
    version: ClassVar[str]
    task_types: ClassVar[list[str]]
    capabilities: ClassVar[dict[str, Any]]
    default_params: ClassVar[dict[str, Any]]
