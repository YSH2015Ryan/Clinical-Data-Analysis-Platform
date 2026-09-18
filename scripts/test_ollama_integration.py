"""Ollama 集成快速验证脚本

用于在开发环境中测试 Ollama Provider 的基本功能，无需启动完整 CDAP 服务。

直接运行（需 Python 3.11+）：
  python scripts/test_ollama_integration.py

容器内运行：
  docker-compose exec backend python scripts/test_ollama_integration.py

环境变量（可选）：
  OLLAMA_BASE_URL: Ollama 服务地址（默认 http://localhost:11434）
  OLLAMA_MODEL: 模型名称（默认 qwen2.5:7b）
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

try:
    from app.services.llm_providers.ollama_provider import OllamaProvider
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("请确保在项目根目录运行，或在容器内运行")
    sys.exit(1)


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_success(text: str):
    print(f"✅ {text}")


def print_error(text: str):
    print(f"❌ {text}")


def print_info(text: str):
    print(f"ℹ️  {text}")


def print_warning(text: str):
    print(f"⚠️  {text}")


async def test_health_check(provider: OllamaProvider) -> bool:
    """测试 1: 健康检查"""
    print_info("测试 Ollama 服务连接...")
    try:
        is_healthy = await provider.health_check()
        if is_healthy:
            print_success(f"Ollama 服务可用: {provider.base_url}")
            return True
        else:
            print_error(f"Ollama 服务不可用: {provider.base_url}")
            print_warning("请确认 Ollama 服务正在运行")
            return False
    except Exception as e:
        print_error(f"健康检查失败: {e}")
        return False


async def test_simple_complete(provider: OllamaProvider) -> bool:
    """测试 2: 简单文本生成"""
    print_info("测试简单文本生成...")
    try:
        prompt = "请用一句话解释什么是逻辑回归。"
        result = await provider.complete(prompt, temperature=0.3, seed=42, max_tokens=100)
        
        if result and len(result) > 10:
            print_success("生成成功")
            print(f"\n提示词: {prompt}")
            print(f"生成结果: {result[:200]}...")
            return True
        else:
            print_error("生成结果为空或过短")
            return False
    except Exception as e:
        print_error(f"生成失败: {e}")
        return False


async def test_generate_with_system(provider: OllamaProvider) -> bool:
    """测试 3: 带系统提示的生成"""
    print_info("测试带系统提示的生成...")
    try:
        system = "你是一位严谨的统计学专家，回答简洁专业。"
        user = "Cox 比例风险模型的核心假设是什么？"
        
        result = await provider.generate_async(
            system=system,
            user=user,
            temperature=0.3,
            seed=42,
            max_tokens=150
        )
        
        if result and len(result) > 10:
            print_success("生成成功")
            print(f"\n系统提示: {system}")
            print(f"用户问题: {user}")
            print(f"生成结果: {result[:200]}...")
            return True
        else:
            print_error("生成结果为空或过短")
            return False
    except Exception as e:
        print_error(f"生成失败: {e}")
        return False


async def test_clinical_interpretation(provider: OllamaProvider) -> bool:
    """测试 4: 临床解读场景"""
    print_info("测试临床数据解读场景...")
    try:
        system = """你是临床数据分析专家。根据统计结果生成专业解读，要求：
1. 使用医学术语
2. 解释统计显著性
3. 提供临床意义
4. 保持客观严谨"""
        
        user = """请解读以下 Cox 回归结果：
- 治疗组 HR=0.65 (95% CI: 0.45-0.89), p=0.008
- 年龄每增加 10 岁 HR=1.23 (95% CI: 1.10-1.38), p<0.001
- 肿瘤分期 III vs I HR=2.45 (95% CI: 1.78-3.21), p<0.001"""
        
        result = await provider.generate_async(
            system=system,
            user=user,
            temperature=0.3,
            seed=42,
            max_tokens=300
        )
        
        if result and len(result) > 50:
            print_success("临床解读生成成功")
            print(f"\n生成结果:\n{result}")
            
            # 简单质量检查
            quality_keywords = ["风险", "显著", "治疗", "生存"]
            found = sum(1 for kw in quality_keywords if kw in result)
            if found >= 2:
                print_success(f"质量检查: 包含 {found}/{len(quality_keywords)} 个关键医学术语")
                return True
            else:
                print_warning(f"质量检查: 仅包含 {found}/{len(quality_keywords)} 个关键医学术语")
                return False
        else:
            print_error("生成结果为空或过短")
            return False
    except Exception as e:
        print_error(f"生成失败: {e}")
        return False


async def test_error_handling(provider: OllamaProvider) -> bool:
    """测试 5: 错误处理"""
    print_info("测试错误处理...")
    try:
        # 测试空提示词
        result = await provider.complete("", temperature=0.3)
        if not result or len(result) < 5:
            print_success("空提示词正确处理（返回空或极短结果）")
            return True
        else:
            print_warning("空提示词生成了有效结果（可能不符合预期）")
            return False
    except Exception as e:
        print_success(f"空提示词触发异常（符合预期）: {type(e).__name__}")
        return True


async def main():
    print_header("Ollama Provider 集成测试")
    
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    
    print_info(f"Ollama 端点: {base_url}")
    print_info(f"模型: {model}")
    print()
    
    # 初始化 provider
    try:
        provider = OllamaProvider(base_url=base_url, model=model)
    except Exception as e:
        print_error(f"初始化失败: {e}")
        return 1
    
    # 运行测试套件
    tests = [
        ("健康检查", test_health_check),
        ("简单文本生成", test_simple_complete),
        ("系统提示生成", test_generate_with_system),
        ("临床解读场景", test_clinical_interpretation),
        ("错误处理", test_error_handling),
    ]
    
    results = []
    for name, test_func in tests:
        print_header(f"测试: {name}")
        try:
            success = await test_func(provider)
            results.append((name, success))
            if not success and name == "健康检查":
                print_error("Ollama 服务不可用，跳过后续测试")
                print_warning("\n请确保 Ollama 服务正在运行:")
                print_warning(f"  docker-compose up -d ollama")
                print_warning(f"或本地启动: ollama serve")
                return 1
        except Exception as e:
            print_error(f"测试异常: {e}")
            results.append((name, False))
    
    # 汇总
    print_header("测试结果汇总")
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅" if success else "❌"
        print(f"{status} {name}")
    
    print()
    if passed == total:
        print_success("所有测试通过！Ollama 集成就绪 🎉")
        return 0
    else:
        print_error(f"部分测试失败: {passed}/{total} 通过")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
