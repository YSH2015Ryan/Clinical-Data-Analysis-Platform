"""
LLM 输出质量验证器

验证 LLM 生成的报告解读是否符合质量标准：
1. 长度控制（80-500字；T6.7 由 100 下调——prompt 要求 150-200 字，
   80 作为可接受下限，避免误杀简洁但合格的输出）
2. 中文占比（≥45%）
3. 数值准确性（防止幻觉，所有数值必须来自 Facts）
4. 格式规范（无序号、分点）
"""

import logging
import re
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class OutputValidator:
    """LLM 输出质量验证器"""

    # 常见的统计阈值，不算幻觉
    COMMON_THRESHOLDS: ClassVar[set[float]] = {0.05, 0.01, 0.001, 0.0001, 1.0, 100.0}

    def validate(self, output: str, facts: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        验证输出质量

        Args:
            output: LLM 生成的文本
            facts: 原始统计数据

        Returns:
            (is_valid, error_messages)
            - is_valid: 是否通过验证
            - error_messages: 错误信息列表
        """
        errors = []

        # 1. 长度检查
        length = len(output)
        if length < 80:
            errors.append(f"输出过短（{length}字 < 80字）")
        elif length > 500:
            errors.append(f"输出过长（{length}字 > 500字）")

        # 2. 中文占比检查
        chinese_count = self._count_chinese_chars(output)
        chinese_ratio = chinese_count / length if length > 0 else 0

        if chinese_ratio < 0.45:
            errors.append(f"中文占比过低（{chinese_ratio * 100:.1f}% < 45%）")

        # 3. 数值验证（防止幻觉）
        hallucinated = self._check_hallucinated_numbers(output, facts)
        if hallucinated:
            errors.append(
                f"检测到幻觉数值（不在 Facts 中）: {', '.join(map(str, hallucinated[:3]))}"
                + (f" 等 {len(hallucinated)} 个" if len(hallucinated) > 3 else "")
            )

        # 4. 格式检查（禁止序号、分点）
        format_issues = self._check_format(output)
        if format_issues:
            errors.extend(format_issues)

        is_valid = len(errors) == 0

        if not is_valid:
            logger.warning(f"Validation failed: {errors}")
        else:
            logger.info(f"Validation passed: {length} chars, {chinese_ratio * 100:.1f}% Chinese")

        return is_valid, errors

    def _count_chinese_chars(self, text: str) -> int:
        """统计中文字符数"""
        return len([c for c in text if "\u4e00" <= c <= "\u9fff"])

    def _check_hallucinated_numbers(self, output: str, facts: dict[str, Any]) -> list[float]:
        """
        检查输出中是否有幻觉数值

        Returns:
            幻觉数值列表（不在 facts 中的数值）
        """
        numbers_in_output = self._extract_numbers(output)
        numbers_in_facts = self._extract_all_numbers(facts)

        hallucinated = []

        for num in numbers_in_output:
            # 跳过常见统计阈值
            if num in self.COMMON_THRESHOLDS:
                continue

            # 检查是否在 facts 中（允许 5% 舍入误差）
            if not any(
                self._is_close(num, fact_num, rel_tol=0.05) for fact_num in numbers_in_facts
            ):
                hallucinated.append(num)

        return hallucinated

    def _extract_numbers(self, text: str) -> list[float]:
        """
        从文本中提取所有数值

        支持格式：123, 123.45, 0.001
        """
        # 匹配整数和小数
        pattern = r"\d+\.?\d*"
        matches = re.findall(pattern, text)

        numbers = []
        for m in matches:
            try:
                num = float(m)
                # 过滤异常大的数（可能是年份、ID等）
                if num < 1e6:
                    numbers.append(num)
            except ValueError:
                continue

        return numbers

    def _extract_all_numbers(self, obj: Any) -> list[float]:
        """
        递归提取字典/列表中的所有数值

        Args:
            obj: 可以是 dict, list, int, float 或其他类型

        Returns:
            数值列表
        """
        numbers = []

        if isinstance(obj, (int, float)):
            numbers.append(float(obj))
        elif isinstance(obj, dict):
            for value in obj.values():
                numbers.extend(self._extract_all_numbers(value))
        elif isinstance(obj, list):
            for item in obj:
                numbers.extend(self._extract_all_numbers(item))

        return numbers

    def _is_close(self, a: float, b: float, rel_tol: float = 0.05) -> bool:
        """
        判断两个数值是否接近（允许舍入误差）

        Args:
            a, b: 要比较的数值
            rel_tol: 相对容差（默认 5%）

        Returns:
            是否接近
        """
        # 绝对容差：相对容差 * 较大值
        abs_tol = rel_tol * max(abs(a), abs(b))
        # 为极小数设置最小容差
        abs_tol = max(abs_tol, 1e-9)

        return abs(a - b) <= abs_tol

    def _check_format(self, text: str) -> list[str]:
        """
        检查格式问题

        Returns:
            格式错误列表
        """
        errors = []

        # 检查是否包含序号
        # 包括：1. 2. 3. 或 ① ② ③ 或 一、二、三、
        if re.search(r"[①②③④⑤⑥⑦⑧⑨⑩]", text):
            errors.append("输出包含圆圈序号（①②③...）")

        if re.search(r"^\s*\d+[\.、\s]+", text, re.MULTILINE):
            errors.append("输出包含数字序号（1. 2. 3...）")

        # 检查是否包含明显的分点词
        # T6.7：仅拦截「首先/其次/最后」典型列举词；「第一点/第二」属叙事表达，
        # 不等于分点排版（原阈值误杀，见 test_validate_format_with_numbers）
        if re.search(r"首先|其次|最后", text):
            errors.append("输出包含分点关键词（首先、其次...）")

        # 检查是否包含 Markdown 标题
        if re.search(r"^[\s]*#+\s+", text, re.MULTILINE):
            errors.append("输出包含 Markdown 标题（# ## ###）")

        return errors


# 全局单例
_validator: OutputValidator | None = None


def get_validator() -> OutputValidator:
    """获取全局验证器实例"""
    global _validator
    if _validator is None:
        _validator = OutputValidator()
    return _validator


def numbers_in(obj: Any) -> list[float]:
    """递归提取 facts 中的所有数值（含字符串文本中的数字，如检验结论里的 p 值）。

    幻觉校验的合法数值域：引擎真实计算值既可能以数值类型出现（metrics），
    也可能嵌在结论文字里（conclusion 字符串），两者都属「来自引擎」。
    """
    validator = get_validator()
    numbers: list[float] = []
    if isinstance(obj, bool):
        return numbers
    if isinstance(obj, int | float):
        numbers.append(float(obj))
    elif isinstance(obj, str):
        numbers.extend(validator._extract_numbers(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            numbers.extend(numbers_in(value))
    elif isinstance(obj, list | tuple):
        for item in obj:
            numbers.extend(numbers_in(item))
    return numbers


def hallucinated_numbers(text: str, facts: Any) -> list[float]:
    """输出文本中不属于 facts 的数值（常见统计阈值豁免）。"""
    validator = get_validator()
    allowed = numbers_in(facts)
    hallucinated: list[float] = []
    for num in validator._extract_numbers(text):
        if num in validator.COMMON_THRESHOLDS:
            continue
        if not any(validator._is_close(num, ref, rel_tol=0.05) for ref in allowed):
            hallucinated.append(num)
    return hallucinated
