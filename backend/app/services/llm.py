"""
LLM 服务统一接口

提供混合模式的 LLM 服务：
- 优先使用本地 Ollama（快速、免费、隐私）
- 本地失败时降级到云端 OpenAI（高质量）
- 强制质量验证（防止幻觉）
"""

import logging
from typing import Dict, Any, Literal, Optional

from .llm_providers.ollama_provider import OllamaProvider
from .llm_providers.openai_provider import OpenAIProvider
from .llm_validators import get_validator

logger = logging.getLogger(__name__)

ModelChoice = Literal["auto", "local", "cloud"]


class LLMService:
    """LLM 服务统一接口"""
    
    def __init__(
        self,
        default_choice: ModelChoice = "auto",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5:7b",
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-4o-mini"
    ):
        """
        初始化 LLM Service
        
        Args:
            default_choice: 默认模型选择策略
            ollama_base_url: Ollama 服务地址
            ollama_model: Ollama 模型名称
            openai_api_key: OpenAI API key
            openai_model: OpenAI 模型名称
        """
        self.default_choice = default_choice
        self.validator = get_validator()
        
        # 初始化本地 provider
        try:
            self.ollama = OllamaProvider(
                base_url=ollama_base_url,
                model=ollama_model
            )
            logger.info(f"Ollama provider initialized: {ollama_model}")
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama provider: {e}")
            self.ollama = None
        
        # 初始化云端 provider（可选）
        self.openai = None
        if openai_api_key:
            try:
                self.openai = OpenAIProvider(
                    api_key=openai_api_key,
                    model=openai_model
                )
                logger.info(f"OpenAI provider initialized: {openai_model}")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI provider: {e}")
    
    def generate_interpretation(
        self,
        facts: Dict[str, Any],
        section_type: str,
        model_choice: Optional[ModelChoice] = None,
        temperature: float = 0.3,
        seed: int = 42
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
        
        # 优先本地
        if choice in ["auto", "local"]:
            if self.ollama:
                try:
                    output = self.ollama.generate(
                        facts=facts,
                        section_type=section_type,
                        temperature=temperature,
                        seed=seed
                    )
                    
                    # 质量验证
                    is_valid, errors = self.validator.validate(output, facts)
                    
                    if is_valid:
                        logger.info(f"Local model success: {section_type}")
                        return output
                    else:
                        logger.warning(
                            f"Local model validation failed: {errors}"
                        )
                        
                        # local 模式下验证失败直接报错
                        if choice == "local":
                            raise ValueError(
                                f"Local model output validation failed: {errors}"
                            )
                        # auto 模式下尝试降级
                        
                except Exception as e:
                    logger.error(f"Local model failed: {e}")
                    
                    # local 模式下直接报错
                    if choice == "local":
                        raise
                    # auto 模式下尝试降级
            else:
                logger.warning("Ollama provider not available")
                
                if choice == "local":
                    raise RuntimeError("Local model not available")
        
        # 降级到云端
        if choice in ["auto", "cloud"]:
            if not self.openai:
                raise RuntimeError(
                    "OpenAI provider not configured. "
                    "Please set OPENAI_API_KEY environment variable."
                )
            
            try:
                output = self.openai.generate(
                    facts=facts,
                    section_type=section_type,
                    temperature=temperature,
                    seed=seed
                )
                
                # 质量验证
                is_valid, errors = self.validator.validate(output, facts)
                
                if is_valid:
                    logger.info(f"Cloud model success: {section_type}")
                    return output
                else:
                    # 云端模型也验证失败，降低标准（只检查致命错误）
                    logger.warning(
                        f"Cloud model validation failed: {errors}, "
                        f"but accepting output anyway"
                    )
                    
                    # 检查是否有致命错误（幻觉数值）
                    has_hallucination = any(
                        "幻觉数值" in err for err in errors
                    )
                    
                    if has_hallucination:
                        raise ValueError(
                            f"Cloud model output contains hallucinated numbers: {errors}"
                        )
                    
                    # 其他错误（长度、格式）可以容忍
                    return output
                    
            except Exception as e:
                logger.error(f"Cloud model failed: {e}")
                raise RuntimeError(
                    f"All available LLM providers failed. Last error: {e}"
                ) from e
        
        # 不应该到达这里
        raise RuntimeError(f"Invalid model choice: {choice}")
    
    def is_local_available(self) -> bool:
        """检查本地模型是否可用"""
        return self.ollama is not None and self.ollama.is_available()
    
    def is_cloud_available(self) -> bool:
        """检查云端模型是否可用"""
        return self.openai is not None and self.openai.is_available()
    
    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        return {
            "local": {
                "available": self.is_local_available(),
                "provider": "Ollama" if self.ollama else None,
                "model": self.ollama.model if self.ollama else None
            },
            "cloud": {
                "available": self.is_cloud_available(),
                "provider": "OpenAI" if self.openai else None,
                "model": self.openai.model if self.openai else None
            },
            "default_choice": self.default_choice
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
    openai_api_key: Optional[str] = None,
    openai_model: str = "gpt-4o-mini"
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
        openai_model=openai_model
    )
    return _llm_service
