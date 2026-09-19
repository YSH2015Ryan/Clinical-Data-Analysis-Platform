"""
LLM Provider 模块

提供多种 LLM 后端的统一接口：
- OllamaProvider: 本地 Ollama 服务（Qwen2.5 7B）
- OpenAIProvider: 云端 OpenAI API（GPT-4o-mini）
- AnthropicProvider: 云端 Anthropic API（Claude 3.5 Sonnet）
"""

from .anthropic_provider import AnthropicProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider

__all__ = ["AnthropicProvider", "OllamaProvider", "OpenAIProvider"]
