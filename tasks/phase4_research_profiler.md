# Task: CDAP高级模型扩展 - Phase 4: 智能推荐系统（精简版）

## 任务类型
软件实现（新功能开发）- Phase 4/7

## 背景
Phase 1-3 已完成（5个模型插件 + 时序CV）。Phase 4 实现智能推荐系统，回答研究设计问题。

## Phase 4 目标
实现研究意图分析引擎，根据数据特征自动推荐模型、研究设计、期刊投稿方向。

## 交付物清单（精简版）

### 1. 研究意图分析引擎
**`backend/app/engines/research_profiler.py`**
- `detect_research_direction(df: pd.DataFrame, user_hints: dict) -> dict`
- **精简版要求**：
  - 回答 3 个研究问题（而非 4 个）：
    1. 研究类型（横断面/队列/病例对照/时序）
    2. 推荐模型（基于数据特征）
    3. 推荐期刊（基于研究类型）
  - 基于规则的决策树（不用 ML）
  - 返回 JSON 结构
  - 符合 CLAUDE.md 分层纪律

### 2. API 端点
**修改 `backend/app/api/v1/datasets.py`**
- 添加 `POST /datasets/{id}/research-profile` 端点
- 调用 research_profiler.detect_research_direction()
- 返回推荐结果

### 3. 单元测试
**`backend/tests/engines/test_research_profiler.py`**
- 至少 6 个测试用例：
  1. `test_detect_cross_sectional` - 横断面研究
  2. `test_detect_cohort_study` - 队列研究
  3. `test_detect_time_series` - 时序研究
  4. `test_recommend_models_regression` - 回归模型推荐
  5. `test_recommend_models_survival` - 生存模型推荐
  6. `test_recommend_journals` - 期刊推荐

**`backend/tests/api/test_research_profile_api.py`**
- 至少 3 个测试用例：
  1. `test_research_profile_endpoint` - API 端点
  2. `test_research_profile_invalid_dataset` - 无效数据集
  3. `test_research_profile_response_structure` - 响应结构

## 设计约束

### 1. 精简版规则
- ❌ 不使用机器学习模型（避免复杂度）
- ✅ 基于规则的决策树
- ✅ 检测数据特征：列数、行数、时间列、事件列、分组列

### 2. 分层纪律
- `research_profiler.py` 属于 engines 层
- ❌ 禁止 import fastapi / celery / sqlalchemy.orm
- ✅ 只依赖 numpy, pandas

### 3. API 契约
- 参考 docs/14-API-Specification.md
- 遵循现有 API 模式

## 参考设计

### research_profiler.py 结构
```python
def detect_research_direction(
    df: pd.DataFrame,
    user_hints: dict | None = None
) -> dict:
    """
    检测研究方向并推荐模型、期刊。
    
    Args:
        df: 数据集
        user_hints: 用户提示（可选），如 {"outcome": "death"}
    
    Returns:
        {
            "research_type": "cohort" | "cross_sectional" | "case_control" | "time_series",
            "recommended_models": ["coxph", "rsf", ...],
            "recommended_journals": ["JAMA", "Lancet", ...],
            "confidence": 0.0-1.0,
            "reasoning": "检测到生存时间列和事件列，推荐队列研究..."
        }
    """
    # 1. 检测研究类型
    research_type = _detect_study_type(df, user_hints)
    
    # 2. 推荐模型
    models = _recommend_models(df, research_type)
    
    # 3. 推荐期刊
    journals = _recommend_journals(research_type)
    
    return {
        "research_type": research_type,
        "recommended_models": models,
        "recommended_journals": journals,
        "confidence": 0.8,
        "reasoning": "..."
    }

def _detect_study_type(df, hints):
    # 检测时间列
    if _has_time_column(df):
        return "time_series"
    
    # 检测生存分析
    if _has_survival_columns(df, hints):
        return "cohort"
    
    # 默认横断面
    return "cross_sectional"

def _recommend_models(df, research_type):
    if research_type == "cohort":
        return ["coxph", "rsf", "deepsurv"]
    elif research_type == "time_series":
        return ["dlnm", "gam"]
    else:
        return ["logreg", "rf", "xgboost"]

def _recommend_journals(research_type):
    # 简化的期刊推荐
    journal_map = {
        "cohort": ["JAMA", "Lancet", "BMJ"],
        "time_series": ["Environmental Health Perspectives", "Epidemiology"],
        "cross_sectional": ["PLOS ONE", "BMC Public Health"]
    }
    return journal_map.get(research_type, ["PLOS ONE"])
```

### API 端点
```python
@router.post("/datasets/{dataset_id}/research-profile")
async def get_research_profile(
    dataset_id: UUID,
    hints: ResearchHintsSchema | None = None,
    db: Session = Depends(get_db)
):
    # 1. 获取数据集
    dataset = await get_dataset_by_id(dataset_id, db)
    
    # 2. 加载数据
    df = load_dataset_dataframe(dataset)
    
    # 3. 调用分析引擎
    from app.engines.research_profiler import detect_research_direction
    result = detect_research_direction(df, hints.dict() if hints else None)
    
    return result
```

## 验收标准
- [ ] research_profiler.py 实现完整
- [ ] API 端点工作正常
- [ ] 9 个测试全部通过（6 + 3）
- [ ] 能返回 3 个研究问题的答案

## 时间预估
- Codex 执行：25-30 分钟
- 测试验证：5 分钟
- 总计：30-35 分钟

## 依赖
- ✅ Phase 1-3 已完成
- ✅ 数据集 API 已存在（/datasets）

## 备注
- 这是精简版，只回答 3 个问题（非原计划的 4 个）
- 基于规则，不用 ML（降低复杂度）
- 期刊推荐是固定映射（不查询真实数据库）
- 足够演示智能推荐概念
