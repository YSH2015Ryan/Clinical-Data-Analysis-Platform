# Task: CDAP高级模型扩展 - Phase 3A: GEE模型

## 任务类型
软件实现（新功能开发）- Phase 3A/7（Phase 3 拆分为 3A + 3B）

## 背景
Phase 1-2 已完成（Poisson/NegBin/GAM/时序CV）。Phase 3 拆分为两个任务避免超时。

## Phase 3A 目标
实现 GEE（广义估计方程）插件，支持重复测量数据、纵向研究。

## 交付物清单

### 1. GEE 插件实现
**`backend/app/plugins/builtin/gee_models.py`**
- GEEAdapter (主类)
- 需求：
  - 继承 `BaseModelAdapter`
  - 使用 statsmodels.GEE 实现
  - 支持 task_types = ["regression", "classification"]
  - 自动检测 grouping variables（重复测量分组）
  - 如果无分组变量，降级到 GLM
  - 返回 OR/RR + 95% CI
  - get_model_fit() 返回 QIC, scale
  - 符合 CLAUDE.md 分层纪律

### 2. 单元测试
**`backend/tests/plugins/test_gee.py`**
- 至少 8 个测试用例：
  1. `test_gee_basic_fit` - 基本拟合（有分组）
  2. `test_gee_no_groups_fallback_glm` - 无分组降级 GLM
  3. `test_gee_auto_detect_groups` - 自动检测分组变量
  4. `test_gee_repeated_measures` - 重复测量数据
  5. `test_gee_working_correlation` - 工作相关矩阵
  6. `test_gee_model_fit_metrics` - QIC/scale 指标
  7. `test_gee_coefficients_ci` - 系数和置信区间
  8. `test_gee_registry_protocol` - 插件注册

### 3. 插件注册
**修改 `backend/pyproject.toml`**
```toml
[project.entry-points."cdap.models"]
gee = "app.plugins.builtin.gee_models:GEEAdapter"
```

## 设计约束

### 1. 蓝图即契约
- 继承 BaseModelAdapter
- 参考 poisson_models.py 和 gam_models.py 结构

### 2. 不重新实现算法
- ✅ 使用 statsmodels.GEE
- ❌ 不自实现 working correlation

### 3. 分层纪律
- 属于 engines 层
- ❌ 禁止 import fastapi / celery / sqlalchemy.orm
- ✅ 只依赖 numpy, pandas, statsmodels

### 4. 特殊要求：自动分组检测
- 检测列名包含 "id", "subject", "patient", "group" 等关键词
- 或者检测列中重复值比例（如 <50% 唯一值可能是分组）
- 如果找不到分组变量，降级到 GLM 并在日志中警告

## 参考资料

### statsmodels GEE 示例
```python
import statsmodels.api as sm
from statsmodels.genmod.families import Gaussian, Binomial
from statsmodels.genmod.cov_struct import Exchangeable

# 分组变量
groups = df['patient_id']

# GEE 拟合
gee = sm.GEE(
    endog=y,
    exog=X,
    groups=groups,
    family=Gaussian(),
    cov_struct=Exchangeable()
)
result = gee.fit()
qic = result.qic
```

### 自动分组检测逻辑
```python
def detect_group_column(X: pd.DataFrame) -> str | None:
    # 1. 检查列名关键词
    for col in X.columns:
        if any(kw in col.lower() for kw in ['id', 'subject', 'patient', 'group']):
            return col
    
    # 2. 检查重复值比例
    for col in X.columns:
        if X[col].dtype in [int, object]:
            unique_ratio = X[col].nunique() / len(X)
            if unique_ratio < 0.5:  # 少于 50% 唯一值
                return col
    
    return None
```

## 验收标准
- [ ] GEEAdapter 实现完整
- [ ] 8 个测试全部通过（容器内）
- [ ] 插件成功注册
- [ ] 自动分组检测工作正常

## 时间预估
- Codex 执行：20-25 分钟
- 测试验证：5 分钟
- 总计：25-30 分钟

## 依赖
- ✅ Phase 1-2 已完成
- ✅ statsmodels 已在 Phase 1 安装
- ❌ 不依赖 Phase 3B

## 备注
- GEE 和 GLM 都在 statsmodels 中，依赖已满足
- 重点是自动分组检测逻辑
- 测试需要构造重复测量数据（每个 subject 多条记录）
