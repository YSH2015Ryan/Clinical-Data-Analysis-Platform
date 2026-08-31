# 智能任务推荐系统改进方案

## 问题分析

### 当前系统的主要问题

1. **过于严格的校验逻辑**
   - RV101 规则强制要求有目标列（severity="blocker"）
   - 直接阻止所有后续操作，即使数据质量完美
   - 没有考虑探索性分析（EDA）场景

2. **LLM 未充分利用**
   - 虽然集成了 Ollama，但仅用于报告生成
   - 没有用于数据集分析和任务类型推荐
   - 缺少智能化的用户引导

3. **缺少探索性分析模式**
   - 系统强制要求预测建模
   - 很多场景只需要描述性统计、相关性分析、可视化

## 改进方案

### 1. 降级 RV101 阻塞级别 ✅

**文件**：`backend/app/engines/validation.py`

```python
# 从 blocker 降级为 warning
Issue(
    "RV101",
    "warning",  # 之前是 "blocker"
    "未自动识别到预测目标列",
    detail="您可以在下一步手动选择目标列，或进行探索性分析（EDA）"
)
```

**效果**：
- ✅ 不再阻塞数据集使用
- ✅ 用户可以手动选择目标列
- ✅ 支持探索性分析流程

### 2. 智能任务推荐系统 ✅

**新文件**：`backend/app/engines/intelligent_task_advisor.py`

**核心功能**：

```python
class IntelligentTaskAdvisor:
    def analyze_dataset(self, df, column_profiles) -> TaskRecommendation:
        """
        调用 LLM 分析数据集，返回：
        - recommended_tasks: 推荐的分析类型
        - recommended_targets: 推荐的目标列
        - unsuitable_tasks: 不适合的分析及原因
        - eda_suggestions: 探索性分析建议
        - can_start_modeling: 是否可以直接建模
        """
```

**LLM Prompt 示例**：

```
你是一个临床数据分析专家。请分析以下数据集：

数据集信息：
- 行数：1500
- 列数：29
- 列详情：
  - Unnamed: 0: numeric, 缺失率 0%, 唯一值数 1500
  - 基础疾病: categorical, 缺失率 5%, 唯一值数 8
  - 术后康复: numeric, 缺失率 2%, 唯一值数 156

请分析：
1. 适合做什么类型的分析？
2. 推荐哪些列作为目标列？
3. 哪些分析不适合？为什么？
4. 建议做哪些探索性分析？

返回 JSON 格式...
```

### 3. 集成到数据集校验流程 ✅

**文件**：`backend/app/workers/dataset_tasks.py`

```python
# 在校验后调用智能推荐
task_recommendation = None
try:
    llm_service = get_llm_service()
    if llm_service.is_available():
        advisor = IntelligentTaskAdvisor(llm_service)
        task_recommendation = advisor.analyze_dataset(df, column_profiles)
except Exception as e:
    logger.warning("task_recommendation_failed", error=str(e))

# 将推荐结果添加到质量报告中
db.add(_quality_report(dataset, version, report, task_recommendation))
```

**推荐结果存储**：

```json
{
  "rule_id": "AI_RECOMMEND",
  "severity": "info",
  "message": "智能任务推荐",
  "detail": {
    "recommended_tasks": ["regression", "classification"],
    "recommended_targets": [
      {
        "column": "术后康复",
        "reason": "该列为数值型，可能表示康复评分",
        "task_type": "regression"
      }
    ],
    "unsuitable_tasks": {
      "time_series": "缺少时间戳列"
    },
    "eda_suggestions": ["相关性分析", "聚类分析"],
    "can_start_modeling": true
  }
}
```

## 前端展示改进（待实现）

### 数据集详情页

```typescript
// 显示智能推荐卡片
<Alert
  type="info"
  icon={<RobotOutlined />}
  message="AI 推荐"
  description={
    <>
      <p><strong>推荐分析类型：</strong>{recommendation.recommended_tasks.join(', ')}</p>
      <p><strong>推荐目标列：</strong></p>
      <ul>
        {recommendation.recommended_targets.map(t => (
          <li key={t.column}>
            {t.column} - {t.reason}
            <Button size="small" onClick={() => selectTarget(t.column)}>
              选择此列
            </Button>
          </li>
        ))}
      </ul>
      {!recommendation.can_start_modeling && (
        <Alert type="warning" message="建议先进行探索性分析" />
      )}
    </>
  }
/>
```

### 分析向导页

```typescript
// 任务类型选择时，灰调不适合的选项
<Radio.Group>
  <Radio value="regression" disabled={isUnsuitable('regression')}>
    回归分析
    {isUnsuitable('regression') && (
      <Tooltip title={unsuitableReason('regression')}>
        <InfoCircleOutlined />
      </Tooltip>
    )}
  </Radio>
  <Radio value="classification">分类分析</Radio>
  <Radio value="eda">
    探索性分析
    <Tag color="blue">推荐</Tag>
  </Radio>
</Radio.Group>
```

## 支持探索性分析（EDA）模式

### 新增 EDA 分析类型

**目标**：支持无目标列的数据探索

**功能**：
1. **描述性统计**
   - 各列分布统计
   - 缺失值分析
   - 异常值检测

2. **相关性分析**
   - 相关系数矩阵热图
   - 变量关系散点图
   - 主成分分析（PCA）

3. **聚类分析**
   - K-means 聚类
   - 层次聚类
   - DBSCAN

4. **数据可视化**
   - 箱线图
   - 直方图
   - 小提琴图

### API 端点（待实现）

```python
@router.post("/analysis-runs", status_code=202)
async def create_analysis_run(body: CreateAnalysisRunRequest):
    # 允许 task_type = "eda"，无需目标列
    if body.task_type == "eda":
        # 执行探索性分析
        return await run_eda_analysis(body.dataset_version_id, body.preprocess_config)
    else:
        # 原有预测建模流程
        return await run_prediction_analysis(...)
```

## 兜底策略

### 当 LLM 不可用时

```python
def _fallback_analysis(df, column_profiles) -> TaskRecommendation:
    """简单规则判断"""
    has_label = any(col.get("semantic_type") == "Label" for col in column_profiles)
    
    if has_label:
        return TaskRecommendation(
            recommended_tasks=["classification", "regression"],
            can_start_modeling=True
        )
    else:
        return TaskRecommendation(
            recommended_tasks=["eda"],
            eda_suggestions=["描述性统计", "相关性分析"],
            can_start_modeling=False
        )
```

## 部署步骤

### 1. 重建后端镜像

```bash
cd D:\Evol-Codex-Test\CDAP\deploy
docker compose build api worker
docker compose up -d api worker
```

### 2. 验证 LLM 可用性

```bash
docker exec cdap-api-1 python -c "
from app.services.llm import get_llm_service
llm = get_llm_service()
print(f'LLM Available: {llm.is_available()}')
print(f'Status: {llm.get_status()}')
"
```

### 3. 测试智能推荐

上传一个没有明显目标列的数据集，查看质量报告中的 `AI_RECOMMEND` issue。

## 预期效果

### 之前（用户痛点）

1. ❌ 上传数据后直接显示 "blocker: 未找到目标列"
2. ❌ 无法进入分析向导
3. ❌ 必须回到 Excel 添加目标列
4. ❌ 即使只想做描述性统计也被阻塞

### 改进后（智能引导）

1. ✅ 上传后显示 warning，不阻塞
2. ✅ AI 推荐：
   - "该数据集适合做探索性分析"
   - "如需预测建模，建议选择 `术后康复` 列作为目标"
   - "不适合时间序列分析：缺少时间戳列"
3. ✅ 可以选择 EDA 模式，查看描述性统计和可视化
4. ✅ 或手动选择推荐的目标列开始建模

## 技术债务

1. **前端实现**：需要在 DatasetDetailPage 和 AnalysisWizardPage 中展示推荐结果
2. **EDA 分析引擎**：需要实现 `run_eda_analysis` 任务
3. **推荐结果缓存**：避免每次查看都调用 LLM
4. **用户反馈机制**：收集推荐准确性，优化 prompt

## 相关文件

- `backend/app/engines/validation.py` - 降级 RV101
- `backend/app/engines/intelligent_task_advisor.py` - 智能推荐引擎（新增）
- `backend/app/workers/dataset_tasks.py` - 集成推荐到校验流程
- `frontend/src/pages/DatasetDetailPage.tsx` - 展示推荐（待实现）
- `frontend/src/pages/AnalysisWizardPage.tsx` - 灰调不适合的选项（待实现）

## 测试用例

### 测试 1：无明显目标列的数据集

**输入**：临床数据采集表2update1.xlsx（29 列，很多 Unnamed）

**预期**：
- 状态：VALIDATED（不再是 FAILED）
- 推荐：EDA 模式
- 建议：补充列名，或手动选择目标列

### 测试 2：有明显目标列的数据集

**输入**：心血管队列基线数据（包含"是否复发"列）

**预期**：
- 推荐：classification
- 推荐目标列："是否复发"
- 可以直接开始建模

### 测试 3：LLM 不可用时

**场景**：Ollama 服务未启动

**预期**：
- 使用兜底规则判断
- 日志记录 task_recommendation_failed
- 不影响数据集校验流程

---

**改进日期**：2026-08-31  
**版本**：Phase 6 T6.6 - 智能任务推荐系统  
**状态**：后端实现完成 / 前端待实现
