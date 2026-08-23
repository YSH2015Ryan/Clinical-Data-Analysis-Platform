# Task: CDAP高级模型扩展 - Phase 1: Poisson/NegBin模型实现

## 任务类型
软件实现（新功能开发）- Phase 1/5

## 背景
CDAP (Clinical Data Analysis Platform) 需扩展统计模型库，支持更多流行病学分析场景。
- 项目位置：D:\Evol-Codex-Test\CDAP
- 约束规范：CLAUDE.md（蓝图即契约、测试先行、100%插件机制、分层纪律）
- 技术栈：Python 3.11 / FastAPI / Celery / PostgreSQL / React 18

## Phase 1 目标
实现 Poisson 回归和负二项回归插件，支持患病率分析、计数数据建模。

## 交付物清单

### 1. 插件实现文件
**`backend/app/plugins/builtin/poisson_models.py`**
- PoissonAdapter (主类)
- NegativeBinomialAdapter (子类)
- 需求：
  - 继承 `BaseModelAdapter` (abstract base in `app/engines/adapters.py`)
  - 使用 statsmodels.api.GLM 实现 Poisson/NegBin 回归
  - 支持 task_types = ["regression"]
  - 返回 rate ratio (RR) + 95% CI
  - get_model_fit() 返回 AIC, BIC, deviance
  - 符合 CLAUDE.md 安全红线：无 eval/exec，参数化输入
  - 引擎独立：禁止 import fastapi / celery / sqlalchemy.orm.Session

### 2. 单元测试
**`backend/tests/plugins/test_poisson.py`**
- 至少 7 个测试用例（根据 docs/19-Test-Plan.md）：
  1. `test_poisson_basic_fit` - 正常拟合验证 RR/CI 格式
  2. `test_poisson_count_outcome` - 计数因变量
  3. `test_negative_binomial_overdispersion` - 过离散数据
  4. `test_negbin_vs_poisson_comparison` - 两者在过离散数据上的差异
  5. `test_categorical_predictors` - 分类自变量处理
  6. `test_missing_values` - 缺失值处理（应报错）
  7. `test_zero_counts` - 全0计数列（边界情况）
- 测试数据：使用 `tests/fixtures/` 下的合成数据
- 覆盖率目标：≥85% (engines/)

### 3. 插件注册
**修改 `backend/pyproject.toml`**
```toml
[project.dependencies]
# 新增依赖
statsmodels = "~=0.14"

[project.entry-points."cdap.models"]
poisson = "app.plugins.builtin.poisson_models:PoissonAdapter"
negbin = "app.plugins.builtin.poisson_models:NegativeBinomialAdapter"
```

## 设计约束

### 1. 蓝图即契约 (CLAUDE.md §1)
- 参考 `docs/07-Model-Execution.md` §3 插件接口规范
- 不得偏离 BaseModelAdapter 抽象接口

### 2. 不重新实现算法 (CLAUDE.md §2)
- ✅ 使用 statsmodels.api.GLM (family=Poisson/NegativeBinomial)
- ❌ 不得自己实现 MLE / IRLS

### 3. 分层纪律 (CLAUDE.md §3)
- `poisson_models.py` 位于 `app/plugins/builtin/` — 属于 engines 层
- ❌ 禁止 `from fastapi import *`
- ❌ 禁止 `from sqlalchemy.orm import Session`
- ✅ 只依赖 numpy, pandas, statsmodels, BaseModelAdapter

### 4. 测试先行 (CLAUDE.md §5)
- 必须先写 `test_poisson.py` 所有7个测试（失败状态）
- 然后实现 `poisson_models.py` 使测试通过

### 5. 结果真实 (CLAUDE.md §8)
- 报告指标必须来自 statsmodels 实际计算值
- 禁止伪造 RR/CI 或硬编码示例数值

## 参考资料

### BaseModelAdapter 接口（docs/07）
```python
class BaseModelAdapter(ABC):
    @property
    @abstractmethod
    def task_types(self) -> list[str]:
        """['regression'] or ['classification'] or ['survival']"""
        
    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> Any:
        """返回训练好的模型对象"""
    
    @abstractmethod
    def predict(self, model: Any, X: pd.DataFrame) -> np.ndarray:
        """返回预测值"""
    
    @abstractmethod
    def get_metrics(self, y_true, y_pred, **kwargs) -> dict:
        """返回评估指标字典，必含 score (主指标)"""
    
    @abstractmethod
    def get_model_fit(self, model: Any) -> dict:
        """返回拟合度信息 (AIC/BIC/R²等)"""
```

### 技术实现提示
**Poisson GLM 代码示例（供参考，非完整实现）**：
```python
import statsmodels.api as sm
from statsmodels.genmod.families import Poisson, NegativeBinomial

# Poisson
model = sm.GLM(y, X, family=Poisson())
result = model.fit()
rr = np.exp(result.params)        # Rate Ratio
conf = np.exp(result.conf_int())  # 95% CI
aic = result.aic
```

### 测试数据要求
- 使用 `tests/fixtures/` 下现有数据或创建合成数据
- 示例：泊松分布 y ~ Poisson(λ=5), n=100
- 过离散示例：y ~ NegativeBinomial(μ=5, α=2)

## 验收标准 (Definition of Done)

### 功能验收
- [ ] PoissonAdapter 和 NegativeBinomialAdapter 实现完整
- [ ] 插件在 `app/engines/model_registry.py` 中成功注册（通过 entry_points）
- [ ] 可通过 API `/api/v1/admin/plugins` 查询到 `poisson` 和 `negbin`

### 测试验收
- [ ] 7 个单元测试全部通过 (pytest)
- [ ] 测试覆盖率 ≥85% (backend/app/plugins/builtin/poisson_models.py)
- [ ] 在 Docker 容器内测试通过（Python 3.11 环境）

### 代码质量验收
- [ ] 通过 Ruff 检查（无 lint 错误）
- [ ] 符合 CLAUDE.md 十条执行规范
- [ ] 分层纪律通过 import-linter 检查（如配置）
- [ ] 类型注解完整（函数签名、返回值）

### 审查验收
- [ ] Evol Codex CLI 执行完成
- [ ] Evol Claude CLI 审查通过 (`review_passed: true`)

## 执行指令

### Evol Codex 执行要求
1. 先创建测试文件 `test_poisson.py`（7个失败测试）
2. 再实现 `poisson_models.py`（使测试通过）
3. 修改 `pyproject.toml` 注册插件
4. 在容器内运行测试：
   ```bash
   docker exec cdap-api-1 pytest backend/tests/plugins/test_poisson.py -v
   ```
5. 如测试失败，修复代码直到全部通过

### Evol Claude 审查要点
1. 验证是否符合 BaseModelAdapter 接口
2. 验证 import 合规（无 fastapi/celery/sqlalchemy.orm）
3. 验证测试覆盖率 ≥85%
4. 验证使用 statsmodels（无自实现算法）
5. 验证测试真实性（无硬编码假数据）

## 时间预估
- Codex 执行：60-90 分钟
- Claude 审查：15-30 分钟
- 总计：1.5-2 小时

## 依赖关系
- ❌ 不依赖其他 Phase（Phase 1 独立）
- ✅ 后续 Phase 2-5 依赖 Phase 1 的插件注册机制验证通过

## 备注
- 本任务是 5 个 Phase 中的第一个，聚焦最简单的 Poisson/NegBin 模型
- 成功标准是 Evol 流程通过 + 测试通过，而非"代码能跑"
- 如遇到 CLAUDE.md 规范冲突，立即停止并报告，不得静默偏离
