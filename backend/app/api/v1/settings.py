"""LLM 运行层设置端点（docs/14 /admin/settings/llm*；T6.6）。

- 部署层（env/docker-compose）管 Ollama 地址与云端总闸；运行层（DB）管策略/开关/key/温度；
- 云端 key 只写不读：落库 Fernet 加密，响应仅掩码回显；
- PUT 后立即热更新全局 LLMService（init_llm_service_from_runtime），无需重启。
"""

import time
from typing import Any

import httpx
from anyio import to_thread
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.config import get_settings
from app.db import get_db
from app.schemas.auth import CurrentUser
from app.schemas.settings import (
    LlmConfigOut,
    LlmFeatureSwitches,
    LlmProviderStatus,
    LlmSettingsOut,
    LlmSettingsUpdate,
    LlmStatus,
    LlmTestRequest,
    LlmTestResult,
    OllamaModelList,
)
from app.services import audit as audit_service
from app.services import settings as settings_service
from app.services.llm import get_llm_service, init_llm_service_from_runtime

router = APIRouter(tags=["admin"])


def _out(cfg: settings_service.LlmRuntimeConfig) -> LlmSettingsOut:
    status = get_llm_service().get_status()

    # 根据 cloud_provider 确定当前 key
    current_key = cfg.anthropic_api_key if cfg.cloud_provider == "anthropic" else cfg.openai_api_key

    return LlmSettingsOut(
        status=LlmStatus(
            local=LlmProviderStatus(**status["local"]),
            cloud=LlmProviderStatus(**status["cloud"]),
            default_choice=status["default_choice"],
        ),
        config=LlmConfigOut(
            model_choice=cfg.model_choice,
            temperature=cfg.temperature,
            ollama_model=cfg.ollama_model,
            cloud_enabled=cfg.cloud_enabled,
            cloud_provider=cfg.cloud_provider,
            cloud_has_key=bool(current_key),
            cloud_key_preview=(settings_service.mask_secret(current_key) if current_key else ""),
            feature_switches=LlmFeatureSwitches(**cfg.feature_switches),
        ),
    )


@router.get("/admin/settings/llm", response_model=LlmSettingsOut)
async def get_llm_settings(
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> LlmSettingsOut:
    return _out(await settings_service.get_llm_config(db))


@router.put("/admin/settings/llm", response_model=LlmSettingsOut)
async def put_llm_settings(
    body: LlmSettingsUpdate,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> LlmSettingsOut:
    cfg = await settings_service.update_llm_config(
        db,
        model_choice=body.model_choice,
        temperature=body.temperature,
        ollama_model=body.ollama_model,
        openai_api_key=body.openai_api_key,
        anthropic_api_key=body.anthropic_api_key,
        cloud_provider=body.cloud_provider,
        feature_switches=(
            dict(body.feature_switches.model_dump()) if body.feature_switches else None
        ),
    )
    await audit_service.record(
        db,
        "admin.llm_settings_update",
        user_id=user.id,
        resource_type="admin_setting",
        resource_id=None,
        # 审计只记变更了哪些键，绝不记值（防 key 泄露进日志）
        detail={"updated_keys": sorted(body.model_dump(exclude_none=True).keys())},
    )
    await db.commit()
    init_llm_service_from_runtime(cfg)  # 热更新，无需重启
    return _out(cfg)


async def _test_local(cfg: settings_service.LlmRuntimeConfig) -> LlmTestResult:
    """真实最小请求测 Ollama 连通与延迟。"""
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{cfg.ollama_base_url}/api/generate",
                json={
                    "model": cfg.ollama_model,
                    "prompt": "回复：ok",
                    "stream": False,
                    "options": {"num_predict": 4},
                },
            )
            latency = int((time.monotonic() - started) * 1000)
            if resp.status_code != 200:
                return LlmTestResult(
                    ok=False,
                    provider="local",
                    latency_ms=latency,
                    detail=f"Ollama 返回 {resp.status_code}",
                )
            return LlmTestResult(ok=True, provider="local", latency_ms=latency)
    except Exception as exc:
        return LlmTestResult(
            ok=False,
            provider="local",
            latency_ms=int((time.monotonic() - started) * 1000),
            detail=f"连接失败：{type(exc).__name__}",
        )


def _test_cloud_sync(cfg: settings_service.LlmRuntimeConfig) -> LlmTestResult:
    started = time.monotonic()
    if not cfg.cloud_enabled:
        return LlmTestResult(ok=False, provider="cloud", latency_ms=0, detail="云端已被部署层禁用")

    # 根据 cloud_provider 选择对应的 key
    if cfg.cloud_provider == "anthropic":
        if not cfg.anthropic_api_key:
            return LlmTestResult(
                ok=False, provider="cloud", latency_ms=0, detail="未配置 Anthropic key"
            )
        try:
            from app.services.llm_providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key=cfg.anthropic_api_key, model=cfg.anthropic_model)
            ok = provider.is_available()
            latency = int((time.monotonic() - started) * 1000)
            return LlmTestResult(
                ok=ok, provider="cloud", latency_ms=latency, detail="" if ok else "Anthropic 不可用"
            )
        except Exception as exc:
            return LlmTestResult(
                ok=False,
                provider="cloud",
                latency_ms=int((time.monotonic() - started) * 1000),
                detail=f"连接失败：{type(exc).__name__}",
            )
    else:  # openai
        if not cfg.openai_api_key:
            return LlmTestResult(
                ok=False, provider="cloud", latency_ms=0, detail="未配置 OpenAI key"
            )
        try:
            from app.services.llm_providers.openai_provider import OpenAIProvider

            openai_provider = OpenAIProvider(api_key=cfg.openai_api_key, model=cfg.openai_model)
            ok = openai_provider.is_available()
            latency = int((time.monotonic() - started) * 1000)
            return LlmTestResult(
                ok=ok, provider="cloud", latency_ms=latency, detail="" if ok else "OpenAI 不可用"
            )
        except Exception as exc:
            return LlmTestResult(
                ok=False,
                provider="cloud",
                latency_ms=int((time.monotonic() - started) * 1000),
                detail=f"连接失败：{type(exc).__name__}",
            )


@router.post("/admin/settings/llm/test", response_model=LlmTestResult)
async def test_llm_provider(
    body: LlmTestRequest,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> LlmTestResult:
    cfg = await settings_service.get_llm_config(db)
    if body.provider == "local":
        return await _test_local(cfg)
    return await to_thread.run_sync(_test_cloud_sync, cfg)


@router.get("/admin/settings/llm/ollama-models", response_model=OllamaModelList)
async def list_ollama_models(
    user: CurrentUser = Depends(require_role("admin")),
) -> OllamaModelList:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code != 200:
                return OllamaModelList(available=False, models=[])
            payload: dict[str, Any] = resp.json()
            names = [str(m.get("name", "")) for m in payload.get("models", [])]
            return OllamaModelList(available=True, models=[n for n in names if n])
    except Exception:
        return OllamaModelList(available=False, models=[])
