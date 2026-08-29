"""
Ollama Provider - 本地 LLM 服务提供者

使用本地 Ollama 服务（Qwen2.5 7B）生成医学统计报告解读。
支持中文输出、数值引用验证、格式控制。
"""

import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


class OllamaProvider:
    """本地 Ollama LLM 提供者"""

    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b", timeout: int = 60
    ):
        """
        初始化 Ollama Provider

        Args:
            base_url: Ollama 服务地址
            model: 模型名称
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

        # 验证连接
        self._verify_connection()

    def _verify_connection(self) -> None:
        """验证 Ollama 服务连接"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code != 200:
                logger.warning(f"Ollama service returned status {response.status_code}")
            else:
                models = response.json().get("models", [])
                model_names = [m["name"] for m in models]
                if self.model not in model_names:
                    logger.warning(
                        f"Model {self.model} not found in Ollama. Available: {model_names}"
                    )
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to Ollama at {self.base_url}: {e}")
            raise RuntimeError(
                f"Cannot connect to Ollama service at {self.base_url}. "
                f"Please ensure Ollama is running."
            ) from e

    def generate(
        self, facts: dict[str, Any], section_type: str, temperature: float = 0.3, seed: int = 42
    ) -> str:
        """
        生成报告解读文本

        Args:
            facts: 结构化的统计数据
            section_type: 章节类型（model_comparison/clinical_interpretation/performance）
            temperature: 生成温度
            seed: 随机种子（确保可复现）

        Returns:
            生成的解读段落

        Raises:
            RuntimeError: Ollama 服务请求失败
        """
        prompt = self._build_prompt(facts, section_type)

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "top_p": 0.9,
                        "seed": seed,
                        "num_predict": 300,  # 限制输出长度
                    },
                },
                timeout=self.timeout,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Ollama API request failed with status {response.status_code}: {response.text}"
                )

            result = response.json()
            output = result.get("response", "")

            if not output:
                raise RuntimeError("Ollama returned empty response")

            # 清理输出格式
            cleaned = self._clean_output(output)

            logger.info(
                f"Generated {len(cleaned)} chars for {section_type}, "
                f"took {result.get('total_duration', 0) / 1e9:.2f}s"
            )

            return cleaned

        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                f"Ollama request timed out after {self.timeout}s. "
                f"Try increasing timeout or use cloud provider."
            ) from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e

    def complete(
        self,
        prompt: str,
        temperature: float = 0.3,
        seed: int = 42,
        max_tokens: int = 600,
    ) -> str:
        """通用补全（T6.7）：自定义 prompt，返回原始文本（不做段落清理，保留 JSON 等结构）。

        Raises:
            RuntimeError: Ollama 服务请求失败
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "top_p": 0.9,
                        "seed": seed,
                        "num_predict": max_tokens,
                    },
                },
                timeout=self.timeout,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Ollama API request failed with status {response.status_code}: {response.text}"
                )
            output = response.json().get("response", "")
            if not output:
                raise RuntimeError("Ollama returned empty response")
            return str(output).strip()
        except requests.exceptions.Timeout as e:
            raise RuntimeError(
                f"Ollama request timed out after {self.timeout}s. "
                "Try increasing timeout or use cloud provider."
            ) from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e

    def _build_prompt(self, facts: dict[str, Any], section_type: str) -> str:
        """
        构建优化的 prompt

        根据医学统计报告的要求，生成结构化的 prompt，
        强调中文输出、禁止序号、控制长度。
        """
        facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
        section_name = self._get_section_name(section_type)
        required_content = self._get_required_content(section_type)
        focus = self._get_focus(section_type)

        return f"""你是医学统计分析专家。请严格按照要求用中文回答。

【重要】输出格式要求：
- 只输出一个完整的段落，不要用任何序号（1.2.3.或①②③）
- 不要分点，不要用"首先、其次、最后"
- 不要用小标题（如"分析："、"结论："）
- 直接开始写段落内容

【内容要求】
- 长度：150-200字
- 必须引用所有Facts中的数值，不得编造
- 先陈述统计显著性，再讨论临床意义或效应量
- 使用被动语态和第三人称
- 用中文，学术论文风格

【示例格式】（仅供参考，不要照抄）
配对t检验显示，随机森林的预测误差显著低于Lasso（t=4.23, p=0.002），
RMSE降低1.18个单位，对应Cohen's d = 1.23（大效应量），表明随机森林
在本数据集上具有明显的预测优势。

现在请根据以下Facts生成「{section_name}」章节的解读段落：

Facts:
{facts_json}

必须引用的内容：{required_content}
重点：{focus}

直接开始写段落，不要其他内容：
"""

    def _clean_output(self, text: str) -> str:
        """
        清理 LLM 输出格式

        去除序号、小标题、合并多段、截断过长内容
        """
        # 1. 去除序号（包括数字序号和圆圈序号）
        text = re.sub(r"^\s*[\d①②③④⑤⑥⑦⑧⑨⑩]+[\.、\s]+", "", text, flags=re.MULTILINE)

        # 2. 去除 Markdown 标题和小标题
        text = re.sub(r"^[\s]*[##*]+\s*.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"【.*?】", "", text)

        # 3. 合并多个段落为一段
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        text = " ".join(paragraphs)

        # 4. 去除多余空行和空格
        text = re.sub(r"\n+", " ", text)
        text = re.sub(r"\s+", " ", text)

        # 5. 截断过长内容（保留完整句子）
        if len(text) > 300:
            # 找最后一个句号；没有合适句号则直接截断
            last_period = text[:300].rfind("。")
            text = text[: last_period + 1] if last_period > 150 else text[:300] + "..."

        return text.strip()

    def _get_section_name(self, section_type: str) -> str:
        """获取章节名称"""
        mapping = {
            "model_comparison": "模型比较与推荐",
            "clinical_interpretation": "临床意义解读",
            "performance": "模型性能分析",
        }
        return mapping.get(section_type, section_type)

    def _get_required_content(self, section_type: str) -> str:
        """获取必须引用的内容"""
        mapping = {
            "model_comparison": "RMSE、t值、p值、效应量（Cohen's d）",
            "clinical_interpretation": "回归系数、置信区间、p值、临床最小重要差异（MCID）",
            "performance": "模型指标（RMSE/AUC等）、统计检验结果、诊断结果",
        }
        return mapping.get(section_type, "所有Facts中的数值")

    def _get_focus(self, section_type: str) -> str:
        """获取重点内容"""
        mapping = {
            "model_comparison": "比较 Top1 和 Top2 模型的性能差异，给出推荐理由",
            "clinical_interpretation": "特征的临床意义、实际影响、是否超过 MCID",
            "performance": "模型性能是否达标、假设是否满足、存在的问题",
        }
        return mapping.get(section_type, "全面解读统计结果")

    def is_available(self) -> bool:
        """
        检查 Ollama 服务是否可用

        Returns:
            True if available, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
