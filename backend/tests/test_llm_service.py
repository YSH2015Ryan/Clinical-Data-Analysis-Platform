"""
LLM Service 单元测试

测试 OllamaProvider, OutputValidator, LLMService 的核心功能
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests

from app.services.llm_providers.ollama_provider import OllamaProvider
from app.services.llm_providers.openai_provider import OpenAIProvider
from app.services.llm_validators import OutputValidator, get_validator
from app.services.llm import LLMService, get_llm_service


class TestOllamaProvider:
    """测试 OllamaProvider"""
    
    def test_init_success(self):
        """测试成功初始化"""
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            provider = OllamaProvider()
            assert provider.model == "qwen2.5:7b"
            assert provider.base_url == "http://localhost:11434"
    
    def test_init_connection_failed(self):
        """测试连接失败"""
        with patch('requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.RequestException("Connection failed")
            
            with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
                OllamaProvider()
    
    def test_generate_success(self):
        """测试成功生成"""
        with patch('requests.get') as mock_get, \
             patch('requests.post') as mock_post:
            
            # Mock 连接验证
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            # Mock 生成请求
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "response": "配对t检验显示，随机森林的预测误差显著低于Lasso（t=4.23, p=0.002）",
                "total_duration": 2000000000  # 2秒
            }
            
            provider = OllamaProvider()
            facts = {
                "rmse_rf": 2.03,
                "rmse_lasso": 3.21,
                "t_stat": 4.23,
                "p_value": 0.002
            }
            
            output = provider.generate(facts, "model_comparison")
            
            assert len(output) > 0
            assert "2.03" in output or "4.23" in output  # 包含数值
            assert "随机森林" in output or "Lasso" in output  # 包含中文
    
    def test_generate_timeout(self):
        """测试超时"""
        with patch('requests.get') as mock_get, \
             patch('requests.post') as mock_post:
            
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            mock_post.side_effect = requests.exceptions.Timeout()
            
            provider = OllamaProvider()
            
            with pytest.raises(RuntimeError, match="timed out"):
                provider.generate({}, "model_comparison")
    
    def test_clean_output(self):
        """测试输出清理"""
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            provider = OllamaProvider()
            
            # 测试去除序号
            text = "1. 第一点\n2. 第二点"
            cleaned = provider._clean_output(text)
            assert "1." not in cleaned
            assert "2." not in cleaned
            
            # 测试去除小标题
            text = "【结论】这是结论"
            cleaned = provider._clean_output(text)
            assert "【结论】" not in cleaned
            
            # 测试合并段落
            text = "第一段\n\n第二段"
            cleaned = provider._clean_output(text)
            assert "\n\n" not in cleaned
    
    def test_is_available(self):
        """测试可用性检查"""
        with patch('requests.get') as mock_get:
            # 第一次调用（初始化）
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            provider = OllamaProvider()
            
            # 第二次调用（is_available）
            mock_get.return_value.status_code = 200
            assert provider.is_available() is True
            
            # 模拟服务不可用
            mock_get.side_effect = requests.exceptions.RequestException()
            assert provider.is_available() is False


class TestOutputValidator:
    """测试 OutputValidator"""
    
    def test_validate_success(self):
        """测试验证通过"""
        validator = OutputValidator()
        
        output = (
            "配对t检验显示，随机森林模型的预测误差显著低于Lasso回归模型，"
            "统计量t等于4.23，对应的p值为0.002，达到统计显著性水平。"
            "均方根误差RMSE降低了1.18个单位，对应的Cohen's d效应量为1.23，"
            "属于大效应量范畴，说明模型改进具有实质性意义。"
        )
        facts = {
            "rmse_rf": 2.03,
            "rmse_lasso": 3.21,
            "t_stat": 4.23,
            "p_value": 0.002,
            "cohens_d": 1.23
        }
        
        is_valid, errors = validator.validate(output, facts)
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_too_short(self):
        """测试输出过短"""
        validator = OutputValidator()
        
        output = "结果显示差异显著。"
        facts = {}
        
        is_valid, errors = validator.validate(output, facts)
        assert is_valid is False
        assert any("过短" in err for err in errors)
    
    def test_validate_too_long(self):
        """测试输出过长"""
        validator = OutputValidator()
        
        output = "这是一个非常长的输出。" * 100  # 超过 500 字
        facts = {}
        
        is_valid, errors = validator.validate(output, facts)
        assert is_valid is False
        assert any("过长" in err for err in errors)
    
    def test_validate_low_chinese_ratio(self):
        """测试中文占比过低"""
        validator = OutputValidator()
        
        output = "The model shows significant difference with p<0.001 and RMSE=2.03 compared to 3.21 in baseline model."
        facts = {"rmse": 2.03, "baseline_rmse": 3.21}
        
        is_valid, errors = validator.validate(output, facts)
        assert is_valid is False
        assert any("中文占比" in err for err in errors)
    
    def test_validate_hallucinated_numbers(self):
        """测试幻觉数值检测"""
        validator = OutputValidator()
        
        output = "配对t检验显示，随机森林的预测误差显著低于Lasso（t=99.99, p=0.002），RMSE降低1.18个单位。"
        facts = {
            "t_stat": 4.23,  # 实际是 4.23，但输出写了 99.99
            "p_value": 0.002
        }
        
        is_valid, errors = validator.validate(output, facts)
        assert is_valid is False
        assert any("幻觉数值" in err for err in errors)
    
    def test_validate_with_common_thresholds(self):
        """测试常见阈值不算幻觉"""
        validator = OutputValidator()
        
        output = "p值小于0.05，表明差异具有统计显著性，模型的RMSE为2.03。"
        facts = {"rmse": 2.03}
        
        is_valid, errors = validator.validate(output, facts)
        # 0.05 是常见阈值，不应该报幻觉
        assert is_valid is True or not any("幻觉" in err for err in errors)
    
    def test_validate_format_with_numbers(self):
        """测试格式检查 - 数字序号"""
        validator = OutputValidator()
        
        output = (
            "分析结果如下：第一点，模型A的均方根误差RMSE为2.03，"
            "表现较好。第二点，模型B的均方根误差RMSE为3.21，"
            "相对较差。综合来看，模型A优于模型B，差异明显。"
        )
        facts = {"rmse_a": 2.03, "rmse_b": 3.21}
        
        is_valid, errors = validator.validate(output, facts)
        # 应该通过，因为没有使用 "1." "2." 这样的序号格式
        assert is_valid is True
    
    def test_validate_format_with_circle_numbers(self):
        """测试格式检查 - 圆圈序号"""
        validator = OutputValidator()
        
        output = "分析结果如下：①模型A的RMSE为2.03。②模型B的RMSE为3.21。"
        facts = {"rmse_a": 2.03, "rmse_b": 3.21}
        
        is_valid, errors = validator.validate(output, facts)
        assert is_valid is False
        assert any("序号" in err for err in errors)
    
    def test_extract_numbers(self):
        """测试数值提取"""
        validator = OutputValidator()
        
        text = "t=4.23, p=0.002, RMSE=2.03"
        numbers = validator._extract_numbers(text)
        
        assert 4.23 in numbers
        assert 0.002 in numbers
        assert 2.03 in numbers
    
    def test_extract_all_numbers_from_dict(self):
        """测试从字典提取所有数值"""
        validator = OutputValidator()
        
        facts = {
            "rmse": 2.03,
            "metrics": {
                "t_stat": 4.23,
                "p_value": 0.002
            },
            "list": [1.23, 3.45]
        }
        
        numbers = validator._extract_all_numbers(facts)
        
        assert 2.03 in numbers
        assert 4.23 in numbers
        assert 0.002 in numbers
        assert 1.23 in numbers
        assert 3.45 in numbers
    
    def test_is_close(self):
        """测试数值接近判断"""
        validator = OutputValidator()
        
        # 相同数值
        assert validator._is_close(2.03, 2.03) is True
        
        # 5% 容差内
        assert validator._is_close(2.03, 2.02) is True
        assert validator._is_close(2.03, 2.13) is True
        
        # 超出容差
        assert validator._is_close(2.03, 3.00) is False
        
        # 极小数
        assert validator._is_close(0.001, 0.0010001) is True
    
    def test_get_validator_singleton(self):
        """测试全局单例"""
        v1 = get_validator()
        v2 = get_validator()
        
        assert v1 is v2


class TestLLMService:
    """测试 LLMService"""
    
    def test_init_with_ollama_only(self):
        """测试只初始化本地模型"""
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            service = LLMService()
            
            assert service.ollama is not None
            assert service.openai is None
    
    def test_generate_with_local_success(self):
        """测试本地模型成功生成"""
        with patch('requests.get') as mock_get, \
             patch('requests.post') as mock_post:
            
            # Mock Ollama
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "response": (
                    "配对t检验显示，随机森林模型的预测误差显著低于Lasso回归模型，"
                    "统计量t值为4.23，对应的p值为0.002，达到统计显著性水平。"
                    "均方根误差RMSE降低了1.18个单位，对应的Cohen's d效应量为1.23，"
                    "属于大效应量范畴，表明随机森林在本数据集上具有明显的预测优势，"
                    "模型改进具有实质性意义。"
                ),
                "total_duration": 2000000000
            }
            
            service = LLMService(default_choice="local")
            
            facts = {
                "rmse_rf": 2.03,
                "rmse_lasso": 3.21,
                "t_stat": 4.23,
                "p_value": 0.002,
                "cohens_d": 1.23
            }
            
            output = service.generate_interpretation(
                facts=facts,
                section_type="model_comparison"
            )
            
            assert len(output) > 0
            assert "4.23" in output
    
    def test_generate_with_local_validation_failed_then_cloud(self):
        """测试本地模型验证失败，降级到云端"""
        with patch('requests.get') as mock_get, \
             patch('requests.post') as mock_post, \
             patch('app.services.llm.OpenAIProvider') as mock_openai_class:
            
            # Mock Ollama
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            # Ollama 返回低质量输出（太短）
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "response": "结果显著。",  # 太短
                "total_duration": 1000000000
            }
            
            # Mock OpenAI
            mock_openai = Mock()
            mock_openai.generate.return_value = "配对t检验显示，随机森林的预测误差显著低于Lasso（t=4.23, p=0.002），RMSE降低1.18个单位，对应Cohen's d = 1.23（大效应量），表明随机森林在本数据集上具有明显的预测优势。"
            mock_openai.is_available.return_value = True
            mock_openai_class.return_value = mock_openai
            
            service = LLMService(
                default_choice="auto",
                openai_api_key="test-key"
            )
            
            facts = {
                "rmse_rf": 2.03,
                "rmse_lasso": 3.21,
                "t_stat": 4.23,
                "p_value": 0.002,
                "cohens_d": 1.23
            }
            
            output = service.generate_interpretation(
                facts=facts,
                section_type="model_comparison"
            )
            
            # 应该使用云端结果
            assert len(output) > 100
            assert "4.23" in output
    
    def test_generate_local_mode_validation_failed_raises(self):
        """测试 local 模式下验证失败直接报错"""
        with patch('requests.get') as mock_get, \
             patch('requests.post') as mock_post:
            
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            # 返回低质量输出
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "response": "短。",
                "total_duration": 1000000000
            }
            
            service = LLMService(default_choice="local")
            
            with pytest.raises(ValueError, match="validation failed"):
                service.generate_interpretation(
                    facts={},
                    section_type="model_comparison"
                )
    
    def test_get_status(self):
        """测试获取服务状态"""
        with patch('requests.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "models": [{"name": "qwen2.5:7b"}]
            }
            
            service = LLMService()
            status = service.get_status()
            
            assert "local" in status
            assert "cloud" in status
            assert status["local"]["available"] is True
            assert status["cloud"]["available"] is False
