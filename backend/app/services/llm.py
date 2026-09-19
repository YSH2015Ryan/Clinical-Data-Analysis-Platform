"""
LLM 服务统一接口

提供混合模式的 LLM 服务：
- 优先使用本地 Ollama（快速、免费、隐私）
- 本地失败时降级到云端 OpenAI/Claude（高质量）
- 强制质量验证（防止幻觉）
"""

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Literal

from app.engines.llm_validators import get_validator

from .llm_privacy import assert_cloud_payload_safe
from .llm_providers.anthropic_provider import AnthropicProvider
from .llm_providers.ollama_provider import OllamaProvider
from .llm_providers.openai_provider import OpenAIProvider

if TYPE_CHECKING:
    from .settings import LlmRuntimeConfig

logger = logging.getLogger(__name__)

ModelChoice = Literal["auto", "local", "cloud"]


class LLMService:
    """LLM 服务统一接口"""

    def __init__(
        self,
        default_choice: ModelChoice = "auto",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5:7b",
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4o-mini",
        anthropic_api_key: str | None = None,
        anthropic_model: str = "claude-3-5-sonnet-20241022",
        cloud_provider: str = "openai",  # "openai" 或 "anthropic"
        cloud_enabled: bool = True,
    ):
        """
        初始化 LLM Service

        Args:
            default_choice: 默认模型选择策略
            ollama_base_url: Ollama 服务地址
            ollama_model: Ollama 模型名称
            openai_api_key: OpenAI API key
            openai_model: OpenAI 模型名称
            anthropic_api_key: Anthropic API key
            anthropic_model: Claude 模型名称
            cloud_provider: 云端提供商选择（openai/anthropic）
            cloud_enabled: 部署层云端总闸（False 时云端路径一律拒绝，T6.6）
        """
        self.default_choice = default_choice
        self.cloud_enabled = cloud_enabled
        self.cloud_provider = cloud_provider
        self.validator = get_validator()

        # 初始化本地 provider
        self.ollama: OllamaProvider | None
        try:
            self.ollama = OllamaProvider(base_url=ollama_base_url, model=ollama_model)
            logger.info(f"Ollama provider initialized: {ollama_model}")
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama provider: {e}")
            self.ollama = None

        # 初始化云端 provider（可选；部署层总闸关闭时跳过）
        self.openai: OpenAIProvider | None = None
        self.anthropic: AnthropicProvider | None = None

        if cloud_enabled:
            if cloud_provider == "openai" and openai_api_key:
                try:
                    self.openai = OpenAIProvider(api_key=openai_api_key, model=openai_model)
                    logger.info(f"OpenAI provider initialized: {openai_model}")
                except Exception as e:
                    logger.warning(f"Failed to initialize OpenAI provider: {e}")

            elif cloud_provider == "anthropic" and anthropic_api_key:
                try:
                    self.anthropic = AnthropicProvider(
                        api_key=anthropic_api_key, model=anthropic_model
                    )
                    logger.info(f"Anthropic provider initialized: {anthropic_model}")
                except Exception as e:
                    logger.warning(f"Failed to initialize Anthropic provider: {e}")

    def generate_interpretation(
        self,
        facts: dict[str, Any],
        section_type: str,
        model_choice: ModelChoice | None = None,
        temperature: float = 0.3,
        seed: int = 42,
    ) -> str:
        """
        生成报告解读文本（带质量验证和降级策略）

        Args:
            facts: 结构化的统计数据
            section_type: 章节类型（model_comparison/clinical_interpretation/performance）
            model_choice: 模型选择（auto/local/cloud），None 表示使用默认值
            temperature: 生成温度
            seed: 随机种子

        Returns:
            生成的解读段落

        Raises:
            RuntimeError: 所有可用的 provider 都失败
        """
        choice = model_choice or self.default_choice

        # 优先本地 Ollama
        if choice in ["auto", "local"]:
            if self.ollama:
                try:
                    output = self.ollama.generate(
                        facts=facts, section_type=section_type, temperature=temperature, seed=seed
                    )

                    # 质量验证
                    is_valid, errors = self.validator.validate(output, facts)

                    if is_valid:
                        logger.info(f"Ollama model success: {section_type}")
                        return output
                    else:
                        logger.warning(f"Ollama validation failed: {errors}")

                        # local 模式下验证失败直接报错
                        if choice == "local":
                            raise ValueError(f"Ollama output validation failed: {errors}")
                        # auto 模式下尝试降级到云端

                except Exception as e:
                    logger.error(f"Ollama failed: {e}")

                    # local 模式下直接报错
                    if choice == "local":
                        raise
                    # auto 模式下尝试降级到云端
            else:
                logger.warning("Ollama provider not available")
                if choice == "local":
                    raise RuntimeError("Local model (Ollama) not available")

        # 降级到云端
        if choice in ["auto", "cloud"]:
            if not self.cloud_enabled:
                raise RuntimeError(
                    "云端 LLM 已被部署层禁用（LLM_CLOUD_ENABLED=false）；"
                    "请改用本地模型或由服务器开发人员开启。"
                )
            # 红线（T6.6）：云端只发聚合统计 facts，行级患者数据禁止出域
            assert_cloud_payload_safe(facts)

            # 选择云端提供商
            cloud_provider = None
            provider_name = ""
            if self.cloud_provider == "anthropic" and self.anthropic:
                cloud_provider = self.anthropic
                provider_name = "Claude"
            elif self.cloud_provider == "openai" and self.openai:
                cloud_provider = self.openai
                provider_name = "OpenAI"
            elif self.openai:  # fallback to OpenAI if configured
                cloud_provider = self.openai
                provider_name = "OpenAI (fallback)"
            elif self.anthropic:  # fallback to Anthropic if configured
                cloud_provider = self.anthropic
                provider_name = "Claude (fallback)"

            if not cloud_provider:
                raise RuntimeError(
                    f"Cloud provider '{self.cloud_provider}' not configured. "
                    "Please set OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable."
                )

            try:
                output = cloud_provider.generate(
                    facts=facts, section_type=section_type, temperature=temperature, seed=seed
                )

                # 质量验证
                is_valid, errors = self.validator.validate(output, facts)

                if is_valid:
                    logger.info(f"{provider_name} success: {section_type}")
                    return output
                else:
                    # 云端模型也验证失败，降低标准（只检查致命错误）
                    logger.warning(
                        f"{provider_name} validation failed: {errors}, but accepting output anyway"
                    )

                    # 检查是否有致命错误（幻觉数值）
                    has_hallucination = any("幻觉数值" in err for err in errors)

                    if has_hallucination:
                        raise ValueError(
                            f"{provider_name} output contains hallucinated numbers: {errors}"
                        )

                    # 其他错误（长度、格式）可以容忍
                    return output

            except Exception as e:
                logger.error(f"{provider_name} failed: {e}")
                raise RuntimeError(f"All available LLM providers failed. Last error: {e}") from e

        # 不应该到达这里
        raise RuntimeError(f"Invalid model choice: {choice}")

    def complete(
        self,
        prompt: str,
        *,
        facts: dict[str, Any] | None = None,
        model_choice: ModelChoice | None = None,
        temperature: float = 0.3,
        seed: int = 42,
        max_tokens: int = 600,
    ) -> str:
        """通用补全（T6.7）：自定义 prompt，按策略走 本地→云端 降级链。

        Args:
            prompt: 完整 prompt（调用方负责把聚合 facts 嵌入其中）
            facts: 云端路径的隐私守卫载荷（只允许聚合统计与列元数据）；
                传 None 表示 prompt 不含任何数据派生内容（云端免校验）
            model_choice: auto（本地优先降级云端）/ local / cloud
            max_tokens: 输出长度上限

        Returns:
            原始输出文本（不做段落清理，调用方自行解析）

        Raises:
            RuntimeError: 所有可用 provider 均失败
        """
        choice = model_choice or self.default_choice

        if choice in ("auto", "local"):
            # 优先 Ollama
            if self.ollama:
                try:
                    result = self.ollama.complete(
                        prompt, temperature=temperature, seed=seed, max_tokens=max_tokens
                    )
                    if inspect.isawaitable(result):
                        result = asyncio.run(result)
                    return str(result)
                except Exception as e:
                    logger.error(f"Ollama complete failed: {e}")
                    if choice == "local":
                        raise
                    # auto 模式下继续到云端降级
            else:
                logger.warning("Ollama provider not available")
                if choice == "local":
                    raise RuntimeError("Local model (Ollama) not available")

        if choice in ("auto", "cloud"):
            if not self.cloud_enabled:
                raise RuntimeError(
                    "云端 LLM 已被部署层禁用（LLM_CLOUD_ENABLED=false）；"
                    "请改用本地模型或由服务器开发人员开启。"
                )
            # 红线（T6.6）：云端只发聚合统计 facts，行级患者数据禁止出域
            if facts is not None:
                assert_cloud_payload_safe(facts)

            # 选择云端提供商
            cloud_provider = None
            if self.cloud_provider == "anthropic" and self.anthropic:
                cloud_provider = self.anthropic
            elif (self.cloud_provider == "openai" and self.openai) or self.openai:
                cloud_provider = self.openai
            elif self.anthropic:
                cloud_provider = self.anthropic

            if not cloud_provider:
                raise RuntimeError("Cloud provider not configured.")

            try:
                return cloud_provider.complete(
                    prompt, temperature=temperature, seed=seed, max_tokens=max_tokens
                )
            except Exception as e:
                raise RuntimeError(f"Cloud model failed: {e}") from e

        raise RuntimeError(f"Invalid model choice: {choice}")

    def is_local_available(self) -> bool:
        """检查本地模型是否可用（Ollama）"""
        return self.ollama is not None and self.ollama.is_available()

    def is_cloud_available(self) -> bool:
        """检查云端模型是否可用"""
        if self.cloud_provider == "anthropic":
            return self.anthropic is not None and self.anthropic.is_available()
        else:
            return self.openai is not None and self.openai.is_available()

    def get_status(self) -> dict[str, Any]:
        """获取服务状态"""
        cloud_info = {}
        if self.cloud_provider == "anthropic" and self.anthropic:
            cloud_info = {
                "available": self.anthropic.is_available()
                if hasattr(self.anthropic, "is_available")
                else True,
                "provider": "Anthropic",
                "model": self.anthropic.model,
                "enabled": self.cloud_enabled,
            }
        elif self.openai:
            cloud_info = {
                "available": self.is_cloud_available(),
                "provider": "OpenAI",
                "model": self.openai.model,
                "enabled": self.cloud_enabled,
            }
        else:
            cloud_info = {
                "available": False,
                "provider": None,
                "model": None,
                "enabled": self.cloud_enabled,
            }

        local_providers = []
        if self.ollama:
            local_providers.append(
                {
                    "name": "Ollama",
                    "model": self.ollama.model,
                    "available": self.ollama.is_available(),
                }
            )

        return {
            "local": {
                "available": self.is_local_available(),
                "providers": local_providers,
            },
            "cloud": cloud_info,
            "default_choice": self.default_choice,
        }


# 全局单例
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """获取全局 LLM Service 实例"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def init_llm_service(
    default_choice: ModelChoice = "auto",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "qwen2.5:7b",
    openai_api_key: str | None = None,
    openai_model: str = "gpt-4o-mini",
    anthropic_api_key: str | None = None,
    anthropic_model: str = "claude-3-5-sonnet-20241022",
    cloud_provider: str = "openai",
    cloud_enabled: bool = True,
) -> LLMService:
    """
    初始化全局 LLM Service

    应该在应用启动时调用一次
    """
    global _llm_service
    _llm_service = LLMService(
        default_choice=default_choice,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=anthropic_model,
        cloud_provider=cloud_provider,
        cloud_enabled=cloud_enabled,
    )
    return _llm_service


def init_llm_service_from_runtime(cfg: "LlmRuntimeConfig") -> LLMService:
    """T6.6：从运行层配置（env 默认 + DB 覆盖）初始化/热更新全局 LLM Service。

    启动时与管理员 PUT /admin/settings/llm 后调用——无需重启服务即可切换模型与策略。
    """
    return init_llm_service(
        default_choice=cfg.model_choice,
        ollama_base_url=cfg.ollama_base_url,
        ollama_model=cfg.ollama_model,
        openai_api_key=cfg.openai_api_key,
        openai_model=cfg.openai_model,
        anthropic_api_key=cfg.anthropic_api_key,
        anthropic_model=cfg.anthropic_model,
        cloud_provider=cfg.cloud_provider,
        cloud_enabled=cfg.cloud_enabled,
    )
