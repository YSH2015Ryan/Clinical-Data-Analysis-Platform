"""
OpenAI Provider - 云端 LLM 服务提供者

使用 OpenAI API（GPT-4o-mini）作为本地模型的备选方案。
作为混合模式中的高质量降级选项。
"""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI LLM 提供者（需要 openai 库）"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        timeout: int = 30
    ):
        """
        初始化 OpenAI Provider
        
        Args:
            api_key: OpenAI API key（默认从环境变量 OPENAI_API_KEY 读取）
            model: 模型名称
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.timeout = timeout
        
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not provided. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )
        
        # 延迟导入 openai（避免未安装时影响 OllamaProvider）
        try:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)
        except ImportError:
            raise ImportError(
                "openai package is required for OpenAIProvider. "
                "Install with: pip install openai"
            )
    
    def generate(
        self,
        facts: Dict[str, Any],
        section_type: str,
        temperature: float = 0.3,
        seed: int = 42
    ) -> str:
        """
        生成报告解读文本
        
        Args:
            facts: 结构化的统计数据
            section_type: 章节类型
            temperature: 生成温度
            seed: 随机种子
            
        Returns:
            生成的解读段落
            
        Raises:
            RuntimeError: OpenAI API 请求失败
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(facts, section_type)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=400,
                seed=seed
            )
            
            output = response.choices[0].message.content

            if not output:
                raise RuntimeError("OpenAI returned empty response")

            logger.info(
                f"Generated {len(output)} chars for {section_type} using {self.model}, "
                f"tokens: {response.usage.total_tokens}"
            )

            return str(output).strip()
            
        except Exception as e:
            raise RuntimeError(f"OpenAI API request failed: {e}") from e
    
    def _build_system_prompt(self) -> str:
        """构建系统 prompt"""
        return """你是医学统计分析专家。你的任务是将结构化的统计分析结果转化为学术论文风格的解读段落。

要求：
1. 只使用提供的 Facts 中的数值，不得编造
2. 输出一个完整的段落（150-200字），不要用序号、分点或小标题
3. 先陈述统计显著性，再讨论临床意义或效应量
4. 使用被动语态和第三人称
5. 用中文，学术论文风格
6. 引用具体的统计检验结果（t值、p值、置信区间等）"""
    
    def _build_user_prompt(self, facts: Dict[str, Any], section_type: str) -> str:
        """构建用户 prompt"""
        facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
        section_name = self._get_section_name(section_type)
        
        return f"""请根据以下统计分析结果，生成「{section_name}」章节的解读段落。

Facts:
{facts_json}

要求：
- 长度：150-200字
- 必须引用所有 Facts 中的数值
- 重点：{self._get_focus(section_type)}

只需输出解读段落，不要其他内容。"""
    
    def _get_section_name(self, section_type: str) -> str:
        """获取章节名称"""
        mapping = {
            "model_comparison": "模型比较与推荐",
            "clinical_interpretation": "临床意义解读",
            "performance": "模型性能分析"
        }
        return mapping.get(section_type, section_type)
    
    def _get_focus(self, section_type: str) -> str:
        """获取重点内容"""
        mapping = {
            "model_comparison": "比较 Top1 和 Top2 模型的性能差异，给出推荐理由",
            "clinical_interpretation": "特征的临床意义、实际影响、是否超过临床最小重要差异",
            "performance": "模型性能是否达标、假设是否满足"
        }
        return mapping.get(section_type, "全面解读统计结果")
    
    def is_available(self) -> bool:
        """
        检查 OpenAI API 是否可用
        
        Returns:
            True if available, False otherwise
        """
        try:
            # 发送一个最小请求测试连接
            self.client.models.list()
            return True
        except Exception:
            return False
