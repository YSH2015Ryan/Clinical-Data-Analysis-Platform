# Task: CDAP高级模型扩展 - Phase 2B: 时序交叉验证

## 任务类型
软件实现（新功能开发）- Phase 2B/6

## 背景
Phase 2A（GAM）已完成。Phase 2B 专注于时序交叉验证工具函数。

## Phase 2B 目标
实现时序交叉验证（滑动窗口CV），保持时间顺序，用于时间序列数据。

## 交付物清单

### 1. 时序交叉验证工具
**`backend/app/engines/preprocessing/timeseries_cv.py`**
- `iter_timeseries_cv_splits(n_samples, n_splits, test_size)` 函数
- 需求：
  - 滑动窗口策略：train 逐步增长，test 固定大小
  - 保持时间顺序（不打乱索引）
  - 返回 (train_idx, test_idx) 元组迭代器
  - sklearn 兼容格式（与 KFold 返回值一致）
  - 完整文档字符串（含示例）
  - 类型注解完整

### 2. 单元测试
**`backend/tests/engines/test_timeseries_cv.py`**
- 至少 8 个测试用例：
  1. `test_timeseries_cv_basic` - 基本滑动窗口
  2. `test_timeseries_cv_train_size_grows` - train 递增
  3. `test_timeseries_cv_test_size_fixed` - test 固定
  4. `test_timeseries_cv_chronological_order` - 时间顺序
  5. `test_timeseries_cv_n_splits` - splits 数量
  6. `test_timeseries_cv_edge_cases` - 边界情况
  7. `test_timeseries_cv_invalid_params` - 非法参数
  8. `test_timeseries_cv_return_format` - 返回格式（numpy array）

## 设计约束

### 1. 分层纪律 (CLAUDE.md §3)
- `timeseries_cv.py` 属于 engines/preprocessing 层
- ❌ 禁止 import fastapi / celery / sqlalchemy.orm
- ✅ 只依赖 numpy, typing

### 2. sklearn 兼容
- 返回格式必须与 `sklearn.model_selection.KFold.split()` 一致
- 每个 split 是 `(train_indices, test_indices)` 元组
- indices 是 `numpy.ndarray` 类型

### 3. 时序特性
- **禁止打乱索引**：必须保持 0, 1, 2, ... 顺序
- **滑动窗口**：train 从小到大增长
- **test 固定**：每个 split 的 test 大小一致

## 参考设计

### 函数签名
```python
def iter_timeseries_cv_splits(
    n_samples: int,
    n_splits: int = 5,
    test_size: int | None = None
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """
    时序交叉验证：滑动窗口，保持时间顺序。
    
    Args:
        n_samples: 总样本数
        n_splits: CV splits 数量
        test_size: 每个 test set 大小（默认 n_samples // (n_splits + 1)）
    
    Yields:
        (train_indices, test_indices): 训练和测试索引数组
    
    Example:
        >>> list(iter_timeseries_cv_splits(100, n_splits=3, test_size=20))
        [(array([0..59]), array([60..79])),
         (array([0..69]), array([70..89])),
         (array([0..79]), array([80..99]))]
    """
    ...
```

### 滑动窗口示例
```
n_samples=100, n_splits=3, test_size=20

Split 1:  train [0:60],  test [60:80]   (train: 60 samples)
Split 2:  train [0:70],  test [70:90]   (train: 70 samples)
Split 3:  train [0:80],  test [80:100]  (train: 80 samples)

注意：
- train 逐步增长（60 -> 70 -> 80）
- test 固定大小（20）
- 无重叠，保持时间顺序
```

## 验收标准
- [ ] `timeseries_cv.py` 实现完整
- [ ] 8 个测试全部通过（容器内）
- [ ] 返回格式与 sklearn 兼容
- [ ] 文档字符串完整（含示例）
- [ ] 类型注解完整

## 时间预估
- Codex 执行：15-20 分钟（单个工具函数）
- 测试验证：5 分钟
- 总计：20-25 分钟

## 依赖
- ✅ Phase 2A 已完成
- ❌ 不依赖其他 Phase
- ⚠️  这是工具函数，不是插件（无需注册 entry_points）

## 备注
- 这是纯工具函数，位于 engines/preprocessing/
- 不需要修改 pyproject.toml（无插件注册）
- 未来会被 DLNM 或其他时序模型使用
- 重点验证时间顺序和滑动窗口逻辑
