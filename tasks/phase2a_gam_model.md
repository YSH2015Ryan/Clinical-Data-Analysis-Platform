# Task: CDAP高级模型扩展 - Phase 2A: GAM模型（拆分任务）

## 任务类型
软件实现（新功能开发）- Phase 2A/6（Phase 2 拆分为 2A + 2B）

## 拆分原因
Phase 2 原任务（GAM + 时序CV）在 30 分钟内超时。拆分为：
- **Phase 2A**：只做 GAM 模型（本任务）
- **Phase 2B**：只做时序 CV（下一个任务）

## Phase 2A 目标
实现 GAM（广义可加模型）插件，支持非线性关系探索。

## 交付物清单

### 1. GAM 插件实现
**`backend/app/plugins/builtin/gam_models.py`**
- GAMAdapter (主类)
- 需求：
  - 继承 `BaseModelAdapter`（参考 poisson_models.py）
  - 使用 pygam.GAM / LogisticGAM
  - 支持 task_types = ["regression", "classification"]
  - 自动检测连续/分类变量
  - 返回 partial dependence curves (JSON)
  - get_model_fit() 返回 AIC, deviance
  - 符合 CLAUDE.md 分层纪律（无 fastapi/celery import）

### 2. 单元测试
**`backend/tests/plugins/test_gam.py`**
- 至少 8 个测试用例（简化版）：
  1. `test_gam_regression_basic` - 回归任务
  2. `test_gam_classification_basic` - 分类任务
  3. `test_gam_nonlinear_relationship` - 非线性关系
  4. `test_gam_categorical_predictors` - 分类变量
  5. `test_gam_continuous_predictors` - 连续变量
  6. `test_gam_partial_dependence` - partial dependence
  7. `test_gam_model_fit_metrics` - AIC/deviance
  8. `test_gam_registry_protocol` - 插件注册

### 3. 插件注册
**修改 `backend/pyproject.toml`**
```toml
[project.dependencies]
pygam = "~=0.9"

[project.entry-points."cdap.models"]
gam = "app.plugins.builtin.gam_models:GAMAdapter"
```

## 设计约束（同 Phase 1）
- 继承 BaseModelAdapter
- 使用 pygam（不自实现）
- 分层纪律（engines 层，无 fastapi/celery）
- 测试先行

## 参考代码

### poisson_models.py 结构（参考）
```python
from app.engines.adapters import BaseModelAdapter
import pandas as pd
import numpy as np
import statsmodels.api as sm

class PoissonAdapter(BaseModelAdapter):
    @property
    def task_types(self) -> list[str]:
        return ["regression"]
    
    def fit(self, X, y, **kwargs):
        # ... implementation
    
    def predict(self, model, X):
        # ... implementation
    
    # ... 其他方法
```

### GAM 示例
```python
from pygam import GAM, LogisticGAM, s, f

# 回归
gam = GAM(s(0) + s(1))  # s=spline for continuous
gam.fit(X, y)

# 分类
gam = LogisticGAM(s(0) + s(1))
gam.fit(X, y)
```

## 验收标准
- [ ] GAMAdapter 实现完整
- [ ] 8 个测试全部通过（容器内）
- [ ] 插件成功注册（entry_points）
- [ ] Codex 执行完成（return_code 0）

## 时间预估
- Codex 执行：20-25 分钟（单个模型）
- 测试验证：5 分钟
- 总计：25-30 分钟

## 依赖
- ✅ Phase 1 已完成（poisson_models.py 可参考）
- ❌ 不依赖 Phase 2B

## 备注
- 专注于 GAM 模型，不涉及时序 CV
- 测试数量减少到 8 个（从 11 个）
- 如果仍然超时，考虑进一步简化测试
