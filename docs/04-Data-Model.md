# 04. 数据模型（Data Model）

> 数据库物理设计（表 DDL、索引）见 [13-Database-Design](13-Database-Design.md)；本章聚焦领域概念模型与数据语义。

## 1. 领域概念 ER 图

```mermaid
erDiagram
    USER ||--o{ PROJECT : owns
    PROJECT ||--o{ DATASET : contains
    PROJECT ||--o{ ANALYSIS_RUN : runs
    DATASET ||--o{ DATASET_VERSION : versions
    DATASET ||--o{ QUALITY_REPORT : has
    DATASET_VERSION ||--o{ QUALITY_REPORT : reports_on
    PROJECT ||--o{ ANALYSIS_RUN : has
    ANALYSIS_RUN ||--|| PREPROCESS_SNAPSHOT : uses
    ANALYSIS_RUN ||--o{ MODEL_RESULT : produces
    ANALYSIS_RUN ||--o| COMPARISON : summarizes
    ANALYSIS_RUN ||--o{ REPORT : generates
    MODEL_PLUGIN ||--o{ MODEL_RESULT : registered_as
    AUDIT_LOG }o--|| USER : actor

    USER {
        uuid id PK
        string email UK
        string password_hash
        string role  "admin|researcher|viewer"
        string display_name
        bool is_active
        timestamptz created_at
    }
    PROJECT {
        uuid id PK
        uuid owner_id FK
        string name
        string description
        jsonb settings
        timestamptz created_at
    }
    DATASET {
        uuid id PK
        uuid project_id FK
        string name
        string source_type "csv|excel|fhir|omop"
        string storage_uri
        string file_hash
        bigint file_size
        string encoding
        string status "UPLOADED|VALIDATED|FAILED|ARCHIVED"
        jsonb column_profile
        timestamptz created_at
    }
    DATASET_VERSION {
        uuid id PK
        uuid dataset_id FK
        int version_no
        string storage_uri
        jsonb transform_log "在线修复操作记录"
        timestamptz created_at
    }
    QUALITY_REPORT {
        uuid id PK
        uuid dataset_id FK
        uuid dataset_version_id FK
        string severity_summary "blockers/warnings counts"
        jsonb issues "规则命中明细"
        jsonb column_profiles
        timestamptz created_at
    }
    ANALYSIS_RUN {
        uuid id PK
        uuid project_id FK
        uuid dataset_version_id FK
        string task_type "survival|classification|regression"
        string status "PENDING|PREPROCESSING|MODELING|COMPARING|COMPLETED|FAILED|CANCELED"
        jsonb preprocess_config
        jsonb selected_models
        jsonb task_detection "自动识别结果+用户确认"
        string celery_chain_id
        text error
        timestamptz created_at
        timestamptz finished_at
    }
    PREPROCESS_SNAPSHOT {
        uuid id PK
        uuid run_id FK
        jsonb steps "有序步骤+参数+统计量"
        string feature_matrix_uri
        string input_hash
    }
    MODEL_RESULT {
        uuid id PK
        uuid run_id FK
        string model_key "如 coxph / rsf / lightgbm"
        string plugin_version
        string status "SUCCESS|FAILED|SKIPPED"
        jsonb metrics "cv mean±std"
        jsonb artifacts "图表/模型文件 uri 列表"
        jsonb explainability "shap/feature_importance 摘要"
        text error
        int duration_ms
    }
    COMPARISON {
        uuid id PK
        uuid run_id FK
        jsonb ranking "有序 model_key + 各指标"
        jsonb recommendation "top3 + 理由"
        jsonb comparison_charts "roc/dca/forest 图 uri"
    }
    REPORT {
        uuid id PK
        uuid run_id FK
        string format "pdf|html|markdown|docx"
        string template_key
        string storage_uri
        string status "PENDING|READY|FAILED"
        timestamptz created_at
    }
    MODEL_PLUGIN {
        string key PK
        string name
        string version
        string task_types "survival|classification|regression"
        jsonb capability "指标/解释能力声明"
        jsonb default_params
        bool enabled
        string entry_point
    }
    AUDIT_LOG {
        bigserial id PK
        uuid user_id FK
        string action
        string resource_type
        uuid resource_id
        jsonb detail
        timestamptz created_at
    }
```

## 2. 核心实体语义

| 实体 | 说明 | 关键设计点 |
|---|---|---|
| Project | 用户工作空间 | 权限隔离边界；settings 存默认预处理偏好 |
| Dataset / DatasetVersion | 原始上传 + 版本化修复 | 原始文件永不覆盖；在线修复产生新版本（可复现） |
| QualityReport | 校验结果 | issues 为结构化 JSON（rule_id/severity/column/rows/message/suggestion），前端直接渲染 |
| AnalysisRun | 一次完整分析 | **参数全快照**（预处理配置/模型集/任务类型）保证可复现；状态机驱动 |
| PreprocessSnapshot | 预处理固化 | 记录每步统计量（均值/编码映射），使未来预测/复跑可重放 |
| ModelResult | 单模型结果 | 指标 JSONB：`{metric: {mean, std, folds[]}}`；失败也落库（error 字段） |
| Comparison | 比较结论 | ranking 为有序数组；recommendation 含自然语言理由模板 |
| Report | 报告产物 | 一次 run 可生成多格式多份 |
| ModelPlugin | 模型注册表 | 数据库存「启用状态/默认参数」，代码实现经 entry_points 加载（见 15 章） |

## 3. 分析结果 JSONB 结构约定

**ModelResult.metrics（分类示例）**
```json
{
  "auc":      {"mean": 0.873, "std": 0.021, "folds": [0.86, 0.88, 0.87, 0.89, 0.86]},
  "accuracy": {"mean": 0.81,  "std": 0.03},
  "precision": {"mean": 0.79}, "recall": {"mean": 0.77}, "f1": {"mean": 0.78},
  "brier":    {"mean": 0.121}
}
```
**生存分析**：`c_index`、`ibs`(integrated brier score)；**回归**：`rmse`、`mae`、`r2`。

**Comparison.recommendation**
```json
{
  "ranking": ["rsf", "coxph", "deepsurv"],
  "top": [
    {"model_key": "rsf", "rank": 1, "reason": "主指标最高（c_index=0.780±0.030），校准/拟合优度最优（ibs=0.120）"},
    {"model_key": "coxph", "rank": 2, "reason": "主指标接近首位（c_index=0.760±0.020，差距 0.020），交叉验证最稳定（std=0.020）"}
  ],
  "not_recommended": [
    {"model_key": "deepsurv", "reason": "交叉验证波动最大（std=0.090）"}
  ],
  "primary_metric": "c_index",
  "formula": "score = 0.6×主指标归一化 + 0.2×稳定性归一化 + 0.2×次级指标归一化（docs/09 §4.1）",
  "scores": [
    {"model_key": "rsf", "score": 0.91, "components": {"primary": 1.0, "stability": 0.6, "secondary": 1.0}}
  ]
}
```
理由由模板引擎基于指标事实生成，只引用真实计算值（docs/09 §4.2）。

## 4. 数据保留与隐私

- 软删除：Dataset/Report 删除 → MinIO 对象标记 + PG 记录 `deleted_at`（字段见 13 章）；管理员可配置保留期后物理清除。
- 数据不出部署边界：平台无任何外部遥测上报。
