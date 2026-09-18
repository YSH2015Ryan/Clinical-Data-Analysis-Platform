"""运行层管理配置服务（T6.6，roadmap 配置分层表）。

- 部署层（环境变量）提供默认值与云端总闸；运行层（DB admin_settings）由管理员界面覆盖；
- is_secret 行 Fernet 加密落库；任何返回值/日志不得泄露明文 key（只回显掩码）。
"""

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import AdminSetting

# LLM 运行层配置键
KEY_MODEL_CHOICE = "llm.model_choice"
KEY_TEMPERATURE = "llm.temperature"
KEY_OLLAMA_MODEL = "llm.ollama_model"
KEY_OPENAI_API_KEY = "llm.openai_api_key"
KEY_ANTHROPIC_API_KEY = "llm.anthropic_api_key"
KEY_CLOUD_PROVIDER = "llm.cloud_provider"
KEY_FEATURE_SWITCHES = "llm.feature_switches"

ModelChoice = Literal["auto", "local", "cloud"]
FeatureSwitch = Literal["off", "local", "local_first", "cloud"]

DEFAULT_FEATURE_SWITCHES: dict[str, FeatureSwitch] = {
    # P0-3：默认 local_first（本地 Ollama 优先，失败回退规则/模板，不出域）；
    # 此前默认全 off 导致未进管理页的部署所有 AI 能力等于不存在（客户反馈「不够智能」）。
    # 每个功能都有规则/模板兜底，Ollama 不可用时行为与 off 等价，仅多一次快速失败探测。
    "research_profile": "local_first",
    "report_interpretation": "local_first",
    "validation_explain": "local_first",
    "iteration": "local_first",  # T6.13 对话式迭代（重跑建议）
    "task_recommend": "local_first",  # T6.6 智能任务推荐 LLM 表达增强（规则结论恒产出）
}


def _fernet() -> Fernet:
    """SETTINGS_ENCRYPTION_KEY 优先；dev 空值时由 JWT_SECRET 派生（prod 由 config 校验拦截）。"""
    settings = get_settings()
    key = settings.settings_encryption_key
    if not key:
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.jwt_secret.encode()).digest()
        ).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


async def get_value(db: AsyncSession, key: str) -> str | None:
    row = await db.get(AdminSetting, key)
    if row is None:
        return None
    if row.is_secret:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value


def _get_value_sync(db: Session, key: str) -> str | None:
    """get_value 的同步版（Celery worker 用 sync Session，T6.7）。"""
    row = db.get(AdminSetting, key)
    if row is None:
        return None
    if row.is_secret:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value


async def set_value(db: AsyncSession, key: str, value: str, *, secret: bool = False) -> None:
    stored = _fernet().encrypt(value.encode()).decode() if secret else value
    row = await db.get(AdminSetting, key)
    if row is None:
        db.add(AdminSetting(key=key, value=stored, is_secret=secret))
    else:
        row.value = stored
        row.is_secret = secret


def mask_secret(plain: str) -> str:
    """掩码回显（key 只写不读）：sk-****abcd；短于 8 字符全掩。"""
    if len(plain) < 8:
        return "****"
    return f"{plain[:3]}****{plain[-4:]}"


@dataclass
class LlmRuntimeConfig:
    """env 默认值 + DB 覆盖后的生效配置。"""

    model_choice: ModelChoice
    temperature: float
    ollama_base_url: str  # 仅部署层（不出现在 PUT）
    ollama_model: str
    openai_model: str  # 仅部署层
    openai_api_key: str | None  # 明文仅在内存，出 API 前必须掩码
    anthropic_model: str  # 仅部署层
    anthropic_api_key: str | None  # 明文仅在内存，出 API 前必须掩码
    cloud_provider: str  # "openai" 或 "anthropic"
    cloud_enabled: bool  # 部署层总闸
    feature_switches: dict[str, FeatureSwitch] = field(
        default_factory=lambda: dict(DEFAULT_FEATURE_SWITCHES)
    )


def _build_config(
    *,
    choice_raw: str | None,
    temperature_raw: str | None,
    switches_raw: str | None,
    ollama_model_raw: str | None,
    openai_api_key: str | None,
    anthropic_api_key: str | None,
    cloud_provider_raw: str | None,
) -> LlmRuntimeConfig:
    """env 默认值 + DB 覆盖的合并逻辑（async/sync 两个入口共用）。"""
    settings = get_settings()
    choice = choice_raw or settings.llm_default_choice
    if choice not in ("auto", "local", "cloud"):
        choice = "auto"
    try:
        temperature = float(temperature_raw) if temperature_raw is not None else 0.3
    except ValueError:
        temperature = 0.3
    switches: dict[str, Any] = dict(DEFAULT_FEATURE_SWITCHES)
    if switches_raw:
        try:
            stored = json.loads(switches_raw)
            for name in DEFAULT_FEATURE_SWITCHES:
                if stored.get(name) in ("off", "local", "local_first", "cloud"):
                    switches[name] = stored[name]
        except (TypeError, ValueError):
            pass  # 损坏配置回退默认（不阻断启动）
    
    cloud_provider = cloud_provider_raw or "openai"
    if cloud_provider not in ("openai", "anthropic"):
        cloud_provider = "openai"
    
    return LlmRuntimeConfig(
        model_choice=choice,  # type: ignore[arg-type]
        temperature=temperature,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=ollama_model_raw or settings.ollama_model,
        openai_model=settings.openai_model,
        openai_api_key=openai_api_key,
        anthropic_model=settings.anthropic_model,
        anthropic_api_key=anthropic_api_key,
        cloud_provider=cloud_provider,
        cloud_enabled=settings.llm_cloud_enabled,
        feature_switches=switches,
    )


async def get_llm_config(db: AsyncSession) -> LlmRuntimeConfig:
    return _build_config(
        choice_raw=await get_value(db, KEY_MODEL_CHOICE),
        temperature_raw=await get_value(db, KEY_TEMPERATURE),
        switches_raw=await get_value(db, KEY_FEATURE_SWITCHES),
        ollama_model_raw=await get_value(db, KEY_OLLAMA_MODEL),
        openai_api_key=await get_value(db, KEY_OPENAI_API_KEY),
        anthropic_api_key=await get_value(db, KEY_ANTHROPIC_API_KEY),
        cloud_provider_raw=await get_value(db, KEY_CLOUD_PROVIDER),
    )


def get_llm_config_sync(db: Session) -> LlmRuntimeConfig:
    """get_llm_config 的同步版（Celery worker 内读取运行层配置，T6.7）。"""
    return _build_config(
        choice_raw=_get_value_sync(db, KEY_MODEL_CHOICE),
        temperature_raw=_get_value_sync(db, KEY_TEMPERATURE),
        switches_raw=_get_value_sync(db, KEY_FEATURE_SWITCHES),
        ollama_model_raw=_get_value_sync(db, KEY_OLLAMA_MODEL),
        openai_api_key=_get_value_sync(db, KEY_OPENAI_API_KEY),
        anthropic_api_key=_get_value_sync(db, KEY_ANTHROPIC_API_KEY),
        cloud_provider_raw=_get_value_sync(db, KEY_CLOUD_PROVIDER),
    )


async def update_llm_config(
    db: AsyncSession,
    *,
    model_choice: ModelChoice | None = None,
    temperature: float | None = None,
    ollama_model: str | None = None,
    openai_api_key: str | None = None,  # None=不动；""=清除；否则覆盖
    anthropic_api_key: str | None = None,  # None=不动；""=清除；否则覆盖
    cloud_provider: str | None = None,  # "openai" 或 "anthropic"
    feature_switches: dict[str, FeatureSwitch] | None = None,
) -> LlmRuntimeConfig:
    if model_choice is not None:
        await set_value(db, KEY_MODEL_CHOICE, model_choice)
    if temperature is not None:
        await set_value(db, KEY_TEMPERATURE, str(temperature))
    if ollama_model is not None:
        await set_value(db, KEY_OLLAMA_MODEL, ollama_model)
    if openai_api_key is not None:
        if openai_api_key == "":
            row = await db.get(AdminSetting, KEY_OPENAI_API_KEY)
            if row is not None:
                await db.delete(row)
        else:
            await set_value(db, KEY_OPENAI_API_KEY, openai_api_key, secret=True)
    if anthropic_api_key is not None:
        if anthropic_api_key == "":
            row = await db.get(AdminSetting, KEY_ANTHROPIC_API_KEY)
            if row is not None:
                await db.delete(row)
        else:
            await set_value(db, KEY_ANTHROPIC_API_KEY, anthropic_api_key, secret=True)
    if cloud_provider is not None:
        if cloud_provider in ("openai", "anthropic"):
            await set_value(db, KEY_CLOUD_PROVIDER, cloud_provider)
    if feature_switches is not None:
        merged = dict(DEFAULT_FEATURE_SWITCHES)
        merged.update(feature_switches)
        await set_value(db, KEY_FEATURE_SWITCHES, json.dumps(merged, ensure_ascii=False))
    return await get_llm_config(db)
