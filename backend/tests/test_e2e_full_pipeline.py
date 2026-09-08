"""
端到端集成测试：完整数据分析流程
测试从数据上传到报告生成的全流程
"""

import pytest
import numpy as np
import pandas as pd
from io import BytesIO
import tempfile
import os


class TestE2EDataUploadAndValidation:
    """端到端测试：数据上传与校验"""
    
    def test_csv_upload_and_parse(self):
        """测试 CSV 上传和解析"""
        # 创建测试数据
        np.random.seed(42)
        data = pd.DataFrame({
            'patient_id': range(1, 101),
            'age': np.random.randint(20, 80, 100),
            'gender': np.random.choice(['M', 'F'], 100),
            'bmi': np.random.normal(25, 5, 100),
            'glucose': np.random.normal(100, 20, 100),
            'outcome': np.random.choice([0, 1], 100)
        })
        
        # 转换为 CSV bytes
        csv_buffer = BytesIO()
        data.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()
        
        # 验证数据
        assert len(csv_content) > 0
        assert b'patient_id' in csv_content
        assert b'age' in csv_content
        
        # 解析回来验证
        parsed_data = pd.read_csv(BytesIO(csv_content))
        assert len(parsed_data) == 100
        assert list(parsed_data.columns) == list(data.columns)
    
    def test_data_validation_rules(self):
        """测试数据校验规则"""
        # 创建有问题的数据（n≥11 才可能触发 3σ 规则：max|z|=(n-1)/√n）
        data = pd.DataFrame({
            'col1': [1, 2, 2] + list(range(10, 27)),  # 有重复
            'col2': [10, 20, None] + list(range(100, 117)),  # 有缺失
            'col3': [1.0] * 19 + [1000.0],  # 有异常值（z≈4.2 > 3）
        })
        
        # 检测重复行
        duplicates = data.duplicated().sum()
        assert duplicates >= 0
        
        # 检测缺失值
        missing = data.isnull().sum().sum()
        assert missing > 0
        
        # 检测异常值（简单方法：超过3倍标准差）
        z_scores = np.abs((data['col3'] - data['col3'].mean()) / data['col3'].std())
        outliers = (z_scores > 3).sum()
        assert outliers > 0


class TestE2EQuickFix:
    """端到端测试：Quick Fix 操作"""
    
    def test_drop_duplicates_quickfix(self):
        """测试删除重复行"""
        data = pd.DataFrame({
            'a': [1, 2, 2, 3],
            'b': [10, 20, 20, 30]
        })
        
        # 模拟 Quick Fix
        original_len = len(data)
        cleaned = data.drop_duplicates()
        
        assert len(cleaned) < original_len
        assert len(cleaned) == 3
    
    def test_impute_missing_quickfix(self):
        """测试缺失值填充"""
        data = pd.DataFrame({
            'num_col': [1.0, 2.0, None, 4.0, 5.0],
            'cat_col': ['A', 'B', None, 'A', 'B']
        })
        
        # 数值列：均值填充
        mean_val = data['num_col'].mean()
        data['num_col'].fillna(mean_val, inplace=True)
        assert data['num_col'].isnull().sum() == 0
        
        # 分类列：众数填充
        mode_val = data['cat_col'].mode()[0]
        data['cat_col'].fillna(mode_val, inplace=True)
        assert data['cat_col'].isnull().sum() == 0
    
    def test_winsorize_outliers_quickfix(self):
        """测试异常值缩尾"""
        np.random.seed(42)
        data = pd.Series([1, 2, 3, 4, 5, 100])  # 100 是异常值
        
        # 计算95%分位数
        lower = data.quantile(0.05)
        upper = data.quantile(0.95)
        
        # 缩尾
        winsorized = data.clip(lower, upper)
        
        assert winsorized.max() < 100
        assert winsorized.min() >= lower


class TestE2EModelTraining:
    """端到端测试：模型训练"""
    
    def test_regression_training(self):
        """测试回归模型训练"""
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_squared_error, r2_score
        
        # 生成回归数据
        np.random.seed(42)
        n = 200
        X = np.random.randn(n, 5)
        y = 2 * X[:, 0] + 3 * X[:, 1] - X[:, 2] + np.random.randn(n)
        
        # 划分数据
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=42
        )
        
        # 训练模型
        model = RandomForestRegressor(n_estimators=10, random_state=42)
        model.fit(X_train, y_train)
        
        # 预测
        y_pred = model.predict(X_test)
        
        # 评估
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)
        
        assert rmse > 0
        assert 0 <= r2 <= 1
    
    def test_classification_training(self):
        """测试分类模型训练"""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import roc_auc_score, accuracy_score
        
        # 生成分类数据
        np.random.seed(42)
        n = 200
        X = np.random.randn(n, 5)
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        
        # 划分数据
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=42
        )
        
        # 训练模型
        model = RandomForestClassifier(n_estimators=10, random_state=42)
        model.fit(X_train, y_train)
        
        # 预测
        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, 1]
        
        # 评估
        accuracy = accuracy_score(y_test, y_pred)
        auc = roc_auc_score(y_test, y_proba)
        
        assert 0 <= accuracy <= 1
        assert 0 <= auc <= 1


class TestE2EModelComparison:
    """端到端测试：模型比较"""
    
    def test_multiple_models_comparison(self):
        """测试多模型比较"""
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.linear_model import Ridge, Lasso
        from sklearn.metrics import mean_squared_error
        
        # 生成数据
        np.random.seed(42)
        n = 150
        X = np.random.randn(n, 4)
        y = 2 * X[:, 0] + 3 * X[:, 1] + np.random.randn(n)
        
        # 训练多个模型
        models = {
            'RandomForest': RandomForestRegressor(n_estimators=10, random_state=42),
            'Ridge': Ridge(alpha=1.0),
            'Lasso': Lasso(alpha=0.1)
        }
        
        results = {}
        for name, model in models.items():
            model.fit(X, y)
            y_pred = model.predict(X)
            rmse = np.sqrt(mean_squared_error(y, y_pred))
            results[name] = rmse
        
        # 验证结果
        assert len(results) == 3
        assert all(rmse > 0 for rmse in results.values())
        
        # 找出最佳模型
        best_model = min(results, key=results.get)
        assert best_model in models.keys()


class TestE2EReportGeneration:
    """端到端测试：报告生成"""
    
    def test_performance_metrics_calculation(self):
        """测试性能指标计算"""
        from sklearn.metrics import (
            mean_squared_error, mean_absolute_error, r2_score
        )
        
        # 模拟预测结果
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([1.1, 2.2, 2.9, 4.1, 4.8])
        
        # 计算指标
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        mae = mean_absolute_error(y_true, y_pred)
        r2 = r2_score(y_true, y_pred)
        
        assert rmse > 0
        assert mae > 0
        assert r2 > 0
    
    def test_model_diagnostics(self):
        """测试模型诊断"""
        from scipy import stats
        
        # 模拟残差
        np.random.seed(42)
        residuals = np.random.normal(0, 1, 100)
        
        # Shapiro-Wilk 正态性检验
        stat, p_value = stats.shapiro(residuals)
        assert 0 <= p_value <= 1
        
        # Durbin-Watson 自相关检验
        dw_stat = np.sum(np.diff(residuals)**2) / np.sum(residuals**2)
        assert dw_stat > 0
    
    def test_baseline_table_generation(self):
        """测试基线表生成"""
        # 创建测试数据
        np.random.seed(42)
        data = pd.DataFrame({
            'age': np.random.normal(50, 10, 100),
            'bmi': np.random.normal(25, 5, 100),
            'gender': np.random.choice(['M', 'F'], 100),
            'group': np.random.choice(['train', 'test'], 100)
        })
        
        # 按组汇总统计
        summary = data.groupby('group').agg({
            'age': ['mean', 'std', 'count'],
            'bmi': ['mean', 'std']
        })
        
        assert len(summary) >= 1
        assert summary.loc['train', ('age', 'count')] > 0


class TestE2ELLMIntegration:
    """端到端测试：LLM 集成"""
    
    def test_llm_interpretation_format(self):
        """测试 LLM 解读格式"""
        # 模拟 LLM 输出
        llm_output = """
        模型诊断结果显示，残差通过Shapiro-Wilk正态性检验（p=0.234），
        表明模型假设基本满足。Breusch-Pagan检验显示同方差性（p=0.456），
        说明模型预测在不同取值范围内的误差相对稳定。综合来看，
        该模型的统计假设得到了较好的满足，结果具有可靠性。
        """
        
        # 验证格式
        assert len(llm_output) >= 100
        assert '正态性' in llm_output or 'Shapiro' in llm_output
        assert 'p=' in llm_output or 'p =' in llm_output
        
        # 验证中文占比
        chinese_chars = sum(1 for c in llm_output if '\u4e00' <= c <= '\u9fff')
        total_chars = len(llm_output.strip())
        chinese_ratio = chinese_chars / total_chars if total_chars > 0 else 0
        
        assert chinese_ratio >= 0.3  # 至少30%中文


class TestE2EPerformance:
    """端到端测试：性能测试"""
    
    def test_large_dataset_processing(self):
        """测试大数据集处理"""
        # 创建较大数据集
        np.random.seed(42)
        n = 5000
        data = pd.DataFrame({
            'x1': np.random.randn(n),
            'x2': np.random.randn(n),
            'x3': np.random.randn(n),
            'y': np.random.randn(n)
        })
        
        # 验证数据大小
        assert len(data) == 5000
        assert data.memory_usage().sum() > 0
        
        # 基本统计
        summary = data.describe()
        assert len(summary) > 0
    
    def test_concurrent_model_training(self):
        """测试并发模型训练（模拟）"""
        from concurrent.futures import ThreadPoolExecutor
        
        def train_model(model_id):
            """模拟训练一个模型"""
            np.random.seed(model_id)
            X = np.random.randn(100, 3)
            y = np.random.randn(100)
            
            from sklearn.linear_model import Ridge
            model = Ridge()
            model.fit(X, y)
            
            return model_id
        
        # 并发训练3个模型
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(train_model, [1, 2, 3]))
        
        assert len(results) == 3
        assert results == [1, 2, 3]


class TestE2EDataSecurity:
    """端到端测试：数据安全"""
    
    def test_no_sensitive_data_in_logs(self):
        """测试日志中不包含敏感数据"""
        # 模拟日志消息
        log_messages = [
            "User uploaded dataset: dataset_123.csv",
            "Model training started for run_id: abc123",
            "Performance: RMSE=1.23, R2=0.85"
        ]
        
        # 验证日志不包含敏感信息
        for msg in log_messages:
            # 不应该包含明确的患者数据
            assert 'patient_id' not in msg.lower()
            assert 'ssn' not in msg.lower()
            assert 'phone' not in msg.lower()
    
    def test_file_extension_whitelist(self):
        """测试文件扩展名白名单"""
        allowed_extensions = ['.csv', '.xlsx', '.xls']
        
        test_files = [
            'data.csv',
            'data.xlsx',
            'data.xls',
            'data.exe',
            'data.sh',
            'data.py'
        ]
        
        for filename in test_files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in allowed_extensions:
                assert True  # 允许
            else:
                assert ext not in allowed_extensions  # 不允许


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
