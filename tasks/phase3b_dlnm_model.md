# Task: CDAP高级模型扩展 - Phase 3B: DLNM模型（简化版）

## 任务类型
软件实现（新功能开发）- Phase 3B/7

## 背景
Phase 1-3A 已完成。Phase 3B 实现 DLNM（分布滞后非线性模型）简化版。

## Phase 3B 目标
实现 DLNM 简化版插件，支持环境流行病学中的滞后效应分析。

## 交付物清单

### 1. DLNM 插件实现
**`backend/app/plugins/builtin/dlnm_models.py`**
- DLNMAdapter (主类)
- **简化版 v0.5**：
  - 继承 `BaseModelAdapter`
  - 使用 numpy/scipy 实现（不依赖 dlnm R 包）
  - 支持 task_types = ["time_series", "regression"]
  - 线性暴露-反应 + 多项式滞后基
  - 返回 lag effect curves (JSON)
  - get_model_fit() 返回 AIC, R²
  - 符合 CLAUDE.md 分层纪律

### 2. 单元测试
**`backend/tests/plugins/test_dlnm.py`**
- 至少 6 个测试用例（简化版）：
  1. `test_dlnm_basic_fit` - 基本拟合
  2. `test_dlnm_lag_structure` - 滞后结构
  3. `test_dlnm_lag_effects` - 滞后效应曲线
  4. `test_dlnm_model_fit_metrics` - AIC/R²
  5. `test_dlnm_time_series_support` - time_series 任务类型
  6. `test_dlnm_registry_protocol` - 插件注册

### 3. 任务类型支持
**修改相关文件以支持 `time_series` 任务类型**：
- `backend/app/engines/model_registry.py` - VALID_TASK_TYPES
- `backend/app/api/v1/admin.py` - TaskTypeQuery
- `backend/app/schemas/analysis.py` - TaskType
- `backend/app/models/entities.py` - CHECK constraint

### 4. 插件注册
**修改 `backend/pyproject.toml`**
```toml
[project.entry-points."cdap.models"]
dlnm = "app.plugins.builtin.dlnm_models:DLNMAdapter"
```

## 设计约束

### 1. 简化版要求
- ❌ 不使用 R 的 dlnm 包（避免 rpy2 依赖）
- ✅ 使用 numpy/scipy 实现简化版
- 线性暴露-反应函数
- 多项式滞后基（2-3 次）
- 足够演示滞后效应概念

### 2. 分层纪律
- 属于 engines 层
- ❌ 禁止 import fastapi / celery / sqlalchemy.orm
- ✅ 只依赖 numpy, pandas, scipy, statsmodels

### 3. 时序任务类型
- 需要在多个文件中添加 `"time_series"`
- 这是系统级修改，影响所有模型
- 必须同步修改 4 个文件

## 参考设计

### DLNM 简化实现思路
```python
import numpy as np
from scipy.interpolate import BSpline

class DLNMAdapter(BaseModelAdapter):
    @property
    def task_types(self) -> list[str]:
        return ["time_series", "regression"]
    
    def fit(self, X, y, **kwargs):
        # 1. 构造滞后矩阵（lag 0 到 lag L）
        lag_matrix = self._create_lag_matrix(X, max_lag=7)
        
        # 2. 多项式滞后权重
        lag_weights = self._polynomial_lag_weights(max_lag=7, degree=2)
        
        # 3. 线性回归拟合
        from sklearn.linear_model import LinearRegression
        model = LinearRegression()
        X_weighted = lag_matrix @ lag_weights
        model.fit(X_weighted, y)
        
        return {'model': model, 'lag_weights': lag_weights}
    
    def _create_lag_matrix(self, X, max_lag):
        # 为每个特征创建滞后变量
        ...
    
    def _polynomial_lag_weights(self, max_lag, degree):
        # 多项式基权重
        ...
```

### time_series 任务类型修改
```python
# model_registry.py
VALID_TASK_TYPES = frozenset({"survival", "classification", "regression", "time_series"})

# admin.py
TaskTypeQuery = Literal["survival", "classification", "regression", "time_series"]

# analysis.py
TaskType = Literal["survival", "classification", "regression", "time_series"]

# entities.py
task_type: Mapped[str] = mapped_column(
    String(20),
    CheckConstraint("task_type IN ('survival','classification','regression','time_series')"),
    nullable=False,
)
```

## 验收标准
- [ ] DLNMAdapter 实现完整（简化版）
- [ ] 6 个测试全部通过（容器内）
- [ ] time_series 任务类型在 4 个文件中添加
- [ ] 插件成功注册
- [ ] 可以返回 lag effect curves

## 时间预估
- Codex 执行：25-30 分钟（模型 + 系统修改）
- 测试验证：5 分钟
- 总计：30-35 分钟

## 依赖
- ✅ Phase 1-3A 已完成
- ✅ numpy/scipy/statsmodels 已安装
- ✅ timeseries_cv.py 已在 Phase 2B 实现

## 备注
- 这是简化版 DLNM，不是完整的 dlnm R 包移植
- 重点是演示滞后效应概念，不追求最优统计性能
- time_series 任务类型的添加是关键系统修改
- 需要创建数据库迁移（如果修改 entities.py）
