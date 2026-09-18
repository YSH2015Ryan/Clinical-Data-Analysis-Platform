# Clinical Data Analysis Platform V2.0 — Update Plan

## 1. 文档目的

本文件用于指导现有 **Clinical Data Analysis Platform** 的 V2.0 升级开发，供 Codex / Claude / 其他 Vibe Coding Agent 作为项目级开发计划和约束文档使用。

本次升级不是简单增加机器学习模型，而是将当前的：

> Clinical Data AutoML Tool

逐步升级为：

> **Clinical Research Data Analysis Copilot**

核心目标：

> 当医学研究者上传一份临床数据后，系统不仅能够自动分析，还能够帮助研究者判断数据是否适合分析、研究问题应该如何定义、分析方法是否合理、哪些结果可能不可信，以及下一步应该做什么。

产品边界：本工具定位为**研究早期辅助与方法学筛查工具**，不是临床决策支持系统，不替代生物统计师 / 流行病学家 / 伦理委员会的审查（详见第 70 节 Disclaimer & Scope of Use）。

---

# 2. 当前项目基础

当前项目已经具备较完整的自动化分析链路：

```text
数据上传
    ↓
数据概览
    ↓
数据质量检查
    ↓
描述性统计
    ↓
单变量分析
    ↓
数据预处理
    ↓
多模型机器学习
    ↓
模型性能比较
    ↓
特征重要性
    ↓
TRIPOD / STROBE 检查
    ↓
HTML 分析报告
```

项目当前已经接入：

```text
Ollama
    ↓
Qwen3.6
    ↓
本地 AI 能力
```

V2.0 应保留已有能力，并在其上建立新的研究工作流、方法学审查和 AI Copilot 层。

---

# 3. 当前实际发现的问题

此前对项目生成的 100,000 行数据分析报告进行审查，发现以下问题。

## 3.1 模型出现完美 AUC

多个模型出现：

```text
CatBoost     AUC = 1.0000
LightGBM     AUC = 1.0000
Logistic     AUC = 1.0000
```

这不能直接解释为“模型性能优秀”。

V2.0 必须把这种情况作为：

```text
Performance Integrity Check
```

触发数据泄漏、重复数据、时间泄漏、目标代理变量等检查。

---

## 3.2 Target Leakage 风险

当前目标变量：

```text
month_group
```

数据中同时存在：

```text
month
Month
date_group
Year
seasons
Jieqi
date
```

这些变量可能能够直接或间接重建目标。

V2.0 必须自动识别这种风险。

---

## 3.3 重复数据

当前报告发现：

```text
17,509 行完全重复记录
```

这可能造成训练集和验证集之间的数据污染，并导致模型性能虚高。

---

## 3.4 临床合理性问题

当前：

```text
age = 598
```

这是明显需要研究者确认的数据质量问题。

系统不能只是将其当作普通 outlier。

---

## 3.5 类别不平衡

当前：

```text
month_group positive rate ≈ 3.5%
```

这种情况下不能只关注 ROC-AUC。

应该增加：

```text
PR-AUC
Sensitivity
Specificity
PPV
NPV
F1
MCC
```

---

## 3.6 当前 Outlier 策略过于机械

当前主要使用：

```text
IQR
Clip
```

需要区分：

```text
Statistical Outlier
Clinical Plausibility Issue
Measurement Error
Potential True Extreme
```

统计异常值不等于临床错误。

---

# 4. V2.0 产品定位

## V1.0

```text
Upload Dataset
    ↓
AutoML
    ↓
Report
```

## V2.0

```text
Upload Dataset
    ↓
Define Research Question
    ↓
Understand Variables
    ↓
Data Quality
    ↓
Leakage Check
    ↓
Analysis Plan
    ↓
Statistical Analysis
    ↓
Prediction Modeling
    ↓
Validation
    ↓
Clinical Interpretation
    ↓
AI Review
    ↓
Research Report
```

---

# 5. V2.0 核心原则

## Principle 1 — AI 不负责制造统计结果

所有数值结果必须由确定性分析引擎计算：

- 样本量
- 缺失率
- 均值
- 中位数
- IQR
- P value
- OR
- HR
- CI
- ROC-AUC
- PR-AUC
- Sensitivity
- Specificity
- PPV
- NPV
- Calibration
- Brier Score

LLM 不得自行计算、修改或猜测这些数字。

---

## Principle 2 — LLM 负责理解和解释

Qwen3.6 主要负责：

- 研究问题理解
- 变量语义辅助理解
- 分析方法解释
- 数据质量问题解释
- 方法学风险审查
- 结果自然语言解释
- 研究问题辅助生成
- 报告生成

---

## Principle 3 — 数据质量优先于模型性能

错误的数据上得到的高 AUC 没有意义。

流程必须优先：

```text
Data Quality
    ↓
Leakage
    ↓
Validation
    ↓
Model Performance
```

---

## Principle 4 — Association ≠ Causation

系统不得把：

```text
相关性
```

自动解释为：

```text
因果关系
```

---

## Principle 5 — Prediction Performance ≠ Clinical Utility

高 AUC 不代表模型已经具备临床应用价值。

---

## Principle 6 — Exploratory Finding ≠ Confirmed Finding

AI 生成的研究方向和假设必须标记：

```text
Hypothesis-generating
```

---

# 6. 总体技术架构

建议形成以下分层：

```text
┌──────────────────────────────┐
│          Web UI              │
│     Research Workspace       │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│      Research Copilot        │
│      Qwen3.6 / Ollama        │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│    Research Planning Layer   │
│ Study Design / Analysis Plan │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│   Statistical Analysis Core  │
│ Python / sklearn / statsmodels│
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│   Clinical Data Quality Core │
│ Leakage / Duplicate / Range  │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│        Data Layer            │
│ CSV / Excel / Parquet        │
└──────────────────────────────┘
```

---

# 7. 第一阶段：代码库审计

## 目标

不要直接重写项目。

首先让 Vibe Coding Agent：

1. 阅读整个 repository
2. 理解当前架构
3. 找到现有数据处理流程
4. 找到统计分析流程
5. 找到机器学习流程
6. 找到报告生成流程
7. 找到 Ollama 集成
8. 找到 Qwen3.6 集成
9. 找到测试体系
10. 识别可以复用的模块

输出：

```text
CURRENT_ARCHITECTURE.md
TECHNICAL_DEBT.md
V2_GAP_ANALYSIS.md
```

这一阶段不得大规模修改代码。

---

# 8. 第二阶段：核心数据模型

建立统一的研究上下文对象。

建议：

```python
StudyContext
DatasetProfile
VariableProfile
DataQualityReport
LeakageReport
AnalysisPlan
AnalysisResult
ModelResult
ClinicalInterpretation
ResearchReport
```

---

# 9. StudyContext

建议包含：

```python
class StudyContext:

    study_name

    research_question

    study_type

    population

    inclusion_criteria

    exclusion_criteria

    exposure

    outcome

    outcome_type

    index_time

    follow_up_period

    prediction_time

    unit_of_analysis

    patient_id

    time_variable

    analysis_goal
```

支持研究类型：

```text
描述性研究
横断面研究
病例对照研究
队列研究
诊断研究
预后研究
风险预测
生存分析
组间比较
相关性分析
探索性研究
```

---

# 10. VariableProfile

每个变量建立统一结构：

```json
{
  "name": "age",
  "display_name": "Age",
  "type": "continuous",
  "unit": "years",
  "clinical_role": "baseline_covariate",
  "timepoint": "baseline",
  "missing_rate": 0.02,
  "unique_count": 82,
  "range": [18, 598],
  "suspected_issue": true
}
```

---

# 11. Variable Dictionary

新增：

```text
Variable Dictionary
```

至少展示：

| Variable | Type | Unit | Clinical Role | Timepoint | Missing | Warning |
|---|---|---|---|---|---:|---|
| age | continuous | years | baseline | T0 | 2% | range issue |
| BMI | continuous | kg/m² | baseline | T0 | 1% | none |
| CRP | continuous | mg/L | biomarker | T0 | 4% | skewed |
| outcome | binary | - | outcome | T1 | 0% | target |

医学参考范围必须记录来源：

```text
User defined
Reference range
Domain knowledge
Dataset inferred
```

不得让 LLM 凭空生成医学参考范围。

---

# 12. 缺失数据机制判断（MCAR / MAR / MNAR）

VariableProfile 目前只记录：

```text
missing_rate
```

仅有缺失率不足以判断插补方法是否合适。同样 20% 的缺失率，如果是完全随机缺失（MCAR），简单插补风险较低；如果缺失本身与结局相关（MNAR），任何插补都可能引入系统性偏倚。

新增模块：

```text
Missing Data Mechanism Check
```

## 判断逻辑（启发式，非严格因果推断）

```text
1. 为每个变量生成缺失指示变量 missing_indicator

2. 检验 missing_indicator 与其他已观测变量的关联
   （卡方检验 / 逻辑回归：missing_indicator ~ other variables）

3. 检验 missing_indicator 与结局变量的关联

4. 综合给出粗略分类：
   Likely MCAR
   Likely MAR
   Possible MNAR
   Undetermined
```

如果缺失与结局显著相关，必须提示：

```text
WARNING

Missingness in "X" is associated with the outcome.
Single imputation may introduce bias.
Consider multiple imputation or a missingness-aware model.
```

## 插补策略与机制匹配

```text
MCAR  → 简单插补（均值 / 中位数 / 众数）风险较低
MAR   → 建议 Multiple Imputation (MICE) 或基于其他变量的回归插补
MNAR  → 任何插补都需谨慎；必须提示研究者并要求确认
```

## 报告要求

必须展示：

```text
Missing Data Mechanism: Likely MCAR / Likely MAR / Possible MNAR / Undetermined
Imputation Method Used
Complete-case vs Imputed comparison（可选，作为敏感性分析）
```

默认原则：不静默插补。插补方法必须在界面上明确展示并由研究者确认。

---

# 13. 第三阶段：Research Question Wizard

上传数据后，不直接要求用户“Run AutoML”。

首先询问：

```text
What are you trying to study?
```

选项：

```text
① 描述患者特征
② 比较两组/多组差异
③ 探索影响因素
④ 研究某因素与结局的关系
⑤ 建立诊断模型
⑥ 建立风险预测模型
⑦ 建立预后模型
⑧ 生存分析
⑨ 探索性数据分析
⑩ 我不确定
```

---

# 14. AI 辅助研究问题定义

Qwen3.6 根据：

```text
研究者自然语言
+
变量元数据
+
数据摘要
```

帮助识别：

```text
Population
Exposure
Outcome
Covariates
Timepoint
Study Design
```

示例：

> 我想研究肺癌患者营养状态是否影响治疗期间并发症。

AI 可以提出：

```text
Population:
肺癌患者

Exposure:
营养状态

Outcome:
治疗期间并发症

Potential Covariates:
年龄
性别
BMI
治疗方式
疾病分期
...
```

但必须显示：

```text
AI-generated suggestion
Researcher confirmation required
```

---

# 15. 第四阶段：Data Quality Gate

当前系统的 Warning 机制升级为：

```text
INFO
WARNING
CRITICAL
BLOCKING
```

---

# 16. Critical Data Quality

例如：

```text
CRITICAL DATA QUALITY ISSUE

The variable "age" contains values outside
the predefined plausible range.

Recommended action:
Review original source data.

Analysis status:
Prediction analysis should not proceed
until this issue is reviewed.
```

严重问题不能只出现在报告末尾。

---

# 17. Duplicate Detection

增加：

```text
Exact duplicate
Patient duplicate
Near duplicate
Repeated measurement
Potential train/test duplication
```

对于：

```text
17,509 duplicate rows
```

系统应该明确提示：

```text
17.5% of records are exact duplicates.

This may artificially inflate model performance
if duplicate records are distributed across
training and validation datasets.
```

操作：

```text
Review duplicates
Exclude duplicates
Keep duplicates
```

不得静默删除。

---

# 18. Patient-level Leakage

如果存在：

```text
patient_id
```

检查同一患者是否进入多个 fold。

如果存在：

```text
GroupKFold
StratifiedGroupKFold
```

应该自动进入候选验证方案。

---

# 19. Sample Size / Power Check（Events Per Variable）

## 背景

当前 100,000 行数据 positive rate ≈ 3.5%，即使排除 target leakage，如果候选预测变量数量偏多，"事件数相对预测变量数不足"本身就会导致模型系数不稳定、过拟合、性能指标虚高。这是**独立于 leakage 之外**的另一个致命问题源，必须单独检查，不能被 leakage 检查覆盖。

## 新增模块

```text
Sample Size / EPV Check
```

## 二分类预测建模

```text
EPV = 少数类事件数 / 候选预测变量数
```

经验阈值：

```text
EPV ≥ 10     OK
5 ≤ EPV < 10 WARNING
EPV < 5      CRITICAL
```

## 生存分析

对应概念：每个协变量所需的非删失事件数（events，而非总样本量）。

## 连续结局（回归任务）

给出基于变量数的最小样本量经验提示（如每个候选预测变量至少 10–20 例观测）。

## 系统行为

```text
1. 该检查必须先于模型训练执行
2. EPV 不足时，在 Data Quality Gate 显示 WARNING / CRITICAL
3. 建议：
   - 精简预测变量（先验临床筛选、正则化、降维）
   - 或将本次分析明确标注为 exploratory-only
4. 结果必须出现在 Executive Summary 中
```

该检查是确定性计算，不使用 LLM。

当系统同时检测到 `AUC ≈ 1.0` 与 `EPV 不足` 时，Performance Integrity Check 的提示中应同时列出两者，说明性能虚高可能是复合原因（leakage + 样本量不足），不能只归因于其中一个。

---

# 20. 第五阶段：Target Leakage Engine

必须实现独立模块：

```text
Leakage Detection Engine
```

检查：

```text
Target Leakage
Feature Leakage
Duplicate Leakage
Patient Leakage
Temporal Leakage
Preprocessing Leakage
ID-related Leakage
Post-outcome Variables
Target Proxy Variables
```

---

# 21. Leakage Rule 1：名称相似

例如：

```text
target = diabetes_status

features:
diabetes
diabetes_result
diabetes_group
diabetes_final
```

标记：

```text
Potential semantic leakage
```

---

# 22. Leakage Rule 2：完全映射

检查：

```text
feature == target
feature == 1-target
```

以及：

```text
corr(feature, target) ≈ 1
```

---

# 23. Leakage Rule 3：目标代理变量

检查：

```text
target
    ↑
feature
```

如果变量能够近似一一重建目标，标记：

```text
Potential target proxy
```

---

# 24. Leakage Rule 4：日期变量

如果：

```text
target = month_group
```

存在：

```text
month
Month
date_group
Year
seasons
Jieqi
date
```

必须提示：

```text
CRITICAL POTENTIAL TARGET LEAKAGE

The target "month_group" appears to be derivable
from one or more date-related variables.

AUC results may therefore reflect deterministic
target reconstruction rather than predictive ability.
```

---

# 25. Leakage Experiment Mode

自动执行敏感性实验：

```text
Model A:
All variables

Model B:
Remove suspicious variables

Model C:
Remove date variables

Model D:
Baseline clinical variables only
```

比较：

```text
AUC
PR-AUC
Sensitivity
Specificity
Calibration
```

示例：

```text
All variables                 AUC 1.00
Without date variables       AUC 0.74
Baseline variables only      AUC 0.71
```

---

# 26. Prediction Time / Time Zero

增加：

```text
Prediction Time
```

研究者指定：

```text
Admission
Before treatment
Before surgery
After first laboratory test
Discharge
```

系统检查预测时点之后才产生的变量。

例如：

```text
Outcome = mortality
Feature = discharge diagnosis
```

提示：

```text
CRITICAL:
Feature may not be available at the intended
prediction time.
```

---

# 27. 第六阶段：统计分析重构

必须拆分：

```text
Association Analysis
```

和：

```text
Prediction Modeling
```

不要继续使用：

```text
Univariate p < 0.05
```

作为预测模型变量筛选的默认方法。

---

# 28. Association Analysis

支持：

```text
t-test
Mann–Whitney U
ANOVA
Kruskal–Wallis
Chi-square
Fisher exact
Correlation
```

输出：

```text
effect size
95% CI
p-value
```

---

# 29. 混杂因素调整 / Confounder Adjustment

Association Analysis（第 26 节）目前止步于单变量关联。医学研究者最常见的真实需求是"控制混杂因素后，X 与 Y 的关系是否仍然成立"，而不只是原始的单变量比较。

## 新增能力

```text
Multivariable Adjusted Regression
（logistic / linear / Cox，根据 outcome_type 自动选择）
```

```text
研究者手动指定候选混杂变量（Confounder List）
系统不自动猜测因果结构，只根据研究者输入执行调整
```

可选（P2 阶段）：

```text
Propensity Score 方法
（matching / IPTW / stratification）
用于观察性研究中比较暴露组间差异
```

## 报告要求

必须区分并同时展示：

```text
Unadjusted association
Adjusted association (adjusted for: age, sex, BMI, ...)
```

明确列出调整变量清单，避免出现"隐藏模型"。

## 与 Principle 4 的关系

即便完成了混杂调整，结果也只能称为：

```text
Adjusted association
```

不能称为：

```text
Causal effect
```

除非研究设计本身支持因果推断（如 RCT、双重差分、断点回归等），且这一判断必须由研究者主动确认，系统不得自动声明因果关系。

---

# 30. 多重比较校正 / Multiple Comparisons Correction

当系统对多个协变量逐一进行单变量检验（批量 t-test / 卡方 / Mann–Whitney 等）时，未校正的 p-value 会系统性虚低，假阳性率随检验数量上升。

## 新增行为

```text
1. 自动识别"批量检验"场景
   （同一结局对 N ≥ 阈值个变量分别做单变量检验）

2. 默认应用 False Discovery Rate
   (Benjamini–Hochberg) 校正

3. 同时展示 raw p-value 和 adjusted p-value

4. 允许研究者切换：
   Bonferroni
   Benjamini–Hochberg
   不校正（选择"不校正"时必须显示警告）
```

## 报告要求

报告中不得只展示未校正 p-value 作为"显著性"结论；显著性描述必须基于校正后的结果，并注明使用的校正方法与检验总数。

---

# 31. Prediction Modeling

变量选择提供：

```text
Pre-specified variables
Clinical variables
Regularization
Embedded methods
Tree-based feature selection
```

报告明确：

```text
Exploratory feature selection
≠
Confirmatory statistical inference
```

---

# 32. 第七阶段：Validation Strategy

当前：

```text
5-fold KFold
```

升级为自动验证策略选择：

```text
KFold
StratifiedKFold
GroupKFold
StratifiedGroupKFold
TimeSeriesSplit
Temporal Validation
Bootstrap
External Validation
```

---

# 33. 验证逻辑

Binary classification：

```text
StratifiedKFold
```

Repeated patient：

```text
GroupKFold
```

Longitudinal：

```text
Temporal validation
```

Multi-center：

```text
Center-based validation
```

---

# 34. Cross-validation Preprocessing

以下步骤必须在 training fold 内 fit：

```text
Imputation
Scaling
Encoding
Feature Selection
Transformation
```

正确：

```text
Train Fold
    ↓
Fit preprocessing
    ↓
Transform Train
    ↓
Transform Validation
```

禁止：

```text
Entire Dataset
    ↓
Fit preprocessing
    ↓
Cross-validation
```

---

# 35. 第八阶段：Outlier Engine

区分：

```text
Statistical Outlier
Clinical Plausibility Issue
Measurement Error
Potential True Extreme
```

策略：

```text
Keep
Winsorize
Clip
Transform
Exclude
Investigate
```

默认：

```text
Keep
```

除非有明确规则或研究者确认。

---

# 36. Clinical Range Engine

支持配置：

```json
{
  "age": {
    "min": 0,
    "max": 120,
    "unit": "years"
  }
}
```

注意：

范围必须记录来源。

---

# 37. 第九阶段：模型评价

模型评价升级为四层：

```text
Discrimination
Calibration
Clinical Utility
Stability
```

---

# 38. Classification Metrics

至少：

```text
ROC-AUC
PR-AUC
Accuracy
Sensitivity
Specificity
PPV
NPV
F1
MCC
Brier Score
```

---

# 39. Threshold Analysis

不能默认：

```text
threshold = 0.5
```

增加：

```text
Threshold
Sensitivity
Specificity
PPV
NPV
```

---

# 40. Calibration

必须增加：

```text
Calibration curve
Calibration intercept
Calibration slope
Brier score
```

---

# 41. Decision Curve Analysis

后续加入：

```text
Decision Curve Analysis
```

展示：

```text
Net Benefit
```

必须标记为：

```text
Exploratory / Clinical Utility Analysis
```

不能直接解释成临床有效性已经得到证明。

---

# 42. ROC / PR / Calibration

核心图表：

```text
ROC Curve
PR Curve
Calibration Curve
Confusion Matrix
```

---

# 43. 模型比较

当前模型 ranking：

```text
0.6 × primary metric
+
0.2 × stability
+
0.2 × secondary metric
```

可以作为内部实验机制保留。

但报告中不要输出：

```text
Winner
Best Model
Top 1
```

改为：

```text
Candidate Models
```

展示：

```text
Performance
Uncertainty
Validation Strategy
Calibration
Stability
Leakage Risk
Data Quality Dependency
```

---

# 44. 连续型结局变量评价 / Continuous Outcome Evaluation

当前模型评价体系（Discrimination / Calibration / Clinical Utility / Stability，第 33–39 节）主要覆盖二分类和生存结局，尚未覆盖连续型结局（例如预测某检验值、住院天数、评分量表分数）。

## 新增指标

```text
RMSE
MAE
R² / Adjusted R²
MAPE（适用时）
```

## 新增图表

```text
Residual Plot
Predicted vs Observed Plot
Calibration-in-the-large（回归版本，检查系统性偏倚）
```

## 与既有流程的关系

Leakage Detection、Data Quality Gate、Validation Strategy、CV Preprocessing 等前序流程对连续结局同样适用，无需单独重建；只有"模型评价"这一层需要按 outcome_type 分支。

## StudyContext 补充

```text
outcome_type:
    binary
    continuous
    time_to_event
    count
    ordinal
```

`outcome_type` 应驱动整个模型评价模块的分支逻辑，而不是只支持二分类。

---

# 45. 第十阶段：Subgroup Analysis

支持：

```text
Age group
Sex
Disease stage
Treatment group
Hospital
Comorbidity
```

展示：

```text
Overall AUC
Male AUC
Female AUC
Age <65 AUC
Age ≥65 AUC
```

如果样本量不足：

```text
Insufficient sample size for reliable subgroup analysis.
```

---

# 46. Interaction Analysis

支持：

```text
Treatment × Age
Treatment × Sex
Biomarker × Disease Stage
```

回归模型输出：

```text
interaction coefficient
95% CI
p-value
```

---

# 47. 第十一阶段：Survival Analysis

如果检测到：

```text
survival_time
event
follow_up
death
progression
```

自动提示：

```text
Potential survival analysis detected.
```

支持：

```text
Kaplan-Meier
Log-rank
Cox proportional hazards
HR
95% CI
```

后续：

```text
Time-dependent ROC
Survival calibration
Competing risks
```

---

# 48. 第十二阶段：Research Copilot

不要简单做：

```text
Chat with Qwen
```

而是：

```text
Research Copilot
```

建议包含：

```text
Data Scientist
Clinical Research Assistant
Statistical Reviewer
ML Reviewer
Medical Report Writer
Research Question Assistant
```

---

# 49. Data Scientist Mode

帮助理解：

```text
数据结构
缺失
异常
重复
变量关系
潜在泄漏
```

---

# 50. Clinical Research Assistant

帮助：

```text
变量解释
统计结果解释
研究设计理解
下一步问题
```

---

# 51. Statistical Reviewer

自动审查：

```text
Sample size
Missing data
Duplicate data
Variable selection
Statistical method
Multiple comparisons
Validation strategy
```

输出：

```text
Major Concerns
Minor Concerns
Questions for Researchers
```

---

# 52. ML Reviewer

自动审查：

```text
Leakage
Overfitting
Validation
Calibration
Class imbalance
Feature importance
```

---

# 53. Clinical Interpretation Assistant

必须避免：

```text
association → causation
prediction → clinical utility
statistical significance → clinical importance
model performance → clinical validation
```

---

# 54. Medical Report Writer

生成：

```text
Methods
Results
Data Quality
Model Performance
Limitations
Next Steps
```

所有数字必须来自 Analysis Engine。

---

# 55. AI Evidence Binding

LLM输出必须引用结构化证据。

例如：

```json
{
  "claim": "The model shows strong discrimination.",
  "evidence": {
    "metric": "roc_auc",
    "value": 0.91,
    "ci": [0.89, 0.93]
  }
}
```

---

# 56. AI Output Validator

自动检查：

```text
AI generated number
        ↓
是否存在于 AnalysisResult？
```

如果不存在：

```text
Reject
```

或：

```text
Needs verification
```

---

# 57. Qwen3.6 / Ollama 架构

必须封装成：

```python
class LLMProvider:

    generate()

    generate_json()

    stream()

    health_check()

    get_model_info()
```

实现：

```text
OllamaProvider
OpenAIProvider
AnthropicProvider
```

不要把 Ollama 调用散落在业务代码中。

---

# 58. Ollama 配置

建议：

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.6
OLLAMA_TIMEOUT=120
OLLAMA_TEMPERATURE=0.2
```

实际模型名必须通过配置，不得硬编码。

---

# 59. AI 任务分级

## Level 0 — Deterministic

不使用 LLM：

```text
Data Quality
Statistics
Metrics
Leakage Detection
Validation
```

## Level 1 — AI Assisted

```text
Variable interpretation
Natural-language summary
```

## Level 2 — Deep AI

```text
Research Design
Methodological Review
Research Question Generation
```

---

# 60. Ollama 不可用时

如果：

```text
Ollama unavailable
```

系统仍必须支持：

```text
Upload
Analysis
Statistics
Machine Learning
Report
```

只提示：

```text
AI Assistant unavailable
```

不能让整个分析平台不可用。

---

# 61. AI Context 管理

禁止将：

```text
300,000 rows
```

直接发送给 LLM。

采用：

```text
Raw Dataset
    ↓
Statistical Summary
    ↓
Data Quality Findings
    ↓
Variable Dictionary
    ↓
Analysis Results
    ↓
Relevant Evidence
    ↓
LLM Context
```

---

# 62. AI Context Object

建议：

```json
{
  "study": {},
  "dataset": {},
  "variables": [],
  "quality": {},
  "leakage": {},
  "statistics": {},
  "models": {},
  "validation": {},
  "limitations": []
}
```

---

# 63. AI Agent 架构

逻辑上拆分：

```text
Research Planner
        ↓
Data Quality Reviewer
        ↓
Statistical Reviewer
        ↓
ML Reviewer
        ↓
Clinical Interpretation Assistant
        ↓
Report Writer
```

第一阶段不需要真正部署多个独立模型。

可以：

```text
一个 Qwen3.6
+
不同 System Prompt
+
结构化 Context
```

---

# 64. AI Guardrails

观察性研究中禁止自动生成：

```text
This proves...
This treatment is effective...
This biomarker causes...
This model is clinically validated...
```

优先：

```text
associated with
observed
suggests
may indicate
requires further validation
```

---

# 65. 自动检查因果语言

如果研究设计属于观察性研究，AI输出中出现：

```text
causes
leads to
results in
```

应触发审查。

---

# 66. 第十三阶段：报告重构

报告名称：

```text
Clinical Research Analysis Report
```

结构：

```text
01 Executive Summary
02 Research Question
03 Dataset
04 Data Quality
05 Critical Risks
06 Variable Dictionary
07 Statistical Analysis
08 Predictive Modeling
09 Model Validation
10 Calibration
11 Subgroup Analysis
12 Feature Interpretation
13 AI Research Review
14 Limitations
15 Suggested Next Steps
16 Technical Appendix
```

---

# 67. Executive Summary

首先显示：

```text
Study Objective
Sample Size
Outcome
Main Findings
Major Data Quality Issues
Major Analysis Risks
Model Performance
Important Limitations
```

---

# 68. Critical Findings

严重问题放在报告前部：

```text
CRITICAL

Potential target leakage detected.

17,509 duplicate records detected.

Age contains implausible values.

Model performance may be inflated.
```

---

# 69. Analysis Status

增加：

```text
GREEN
Analysis suitable for interpretation

YELLOW
Analysis completed but important limitations exist

RED
Major data or methodological problems detected
```

状态由规则系统决定，不由 LLM 决定。

---

# 70. 免责声明与使用边界 / Disclaimer & Scope of Use

## 固定声明文本

报告与产品界面必须包含以下声明，且不得由 LLM 生成或改写：

```text
This tool is designed to support early-stage clinical research
data exploration and methodological screening.

It does NOT constitute medical advice, a clinical decision-support
system, or a substitute for consultation with a qualified
biostatistician, epidemiologist, or the study's IRB/ethics committee.

Results, especially those generated under Exploratory Mode or under
a RED analysis status, must not be used to guide patient care or be
presented as confirmatory findings without independent statistical
review.
```

## 展示要求

```text
Analysis Status = RED
        或
用户主动进入 Exploratory Mode（见第 66 节 Critical Issue Gate）
        ↓
声明必须以醒目样式（如红色横幅）出现在：
    报告首页
    UI 顶部
而不仅仅是页脚小字
```

该声明是产品的固定组成部分，属于 Level 0（Deterministic）内容，不属于 AI 生成内容。

---

# 71. 第十四阶段：Research Workflow

最终工作流：

```text
Step 1  Upload Dataset
Step 2  Define Research Question
Step 3  Understand Variables
Step 4  Data Quality Check
Step 5  Leakage Check
Step 6  Analysis Plan
Step 7  Statistical Analysis
Step 8  Prediction Modeling
Step 9  Model Validation
Step 10 Clinical Interpretation
Step 11 AI Review
Step 12 Generate Report
```

---

# 72. Critical Issue Gate

如果发现：

```text
CRITICAL leakage
```

用户点击：

```text
Run Model
```

系统提示：

```text
Critical methodological issue detected.

[Review issue]
[Continue exploratory analysis]
[Return to data cleaning]
```

如果用户继续：

```text
Exploratory Mode
```

报告必须明确：

```text
Results should not be interpreted as unbiased
predictive performance.
```

---

# 73. 第十五阶段：300,000 行数据性能

目标数据规模：

```text
300,000 rows
```

避免大量：

```python
df.copy()
```

根据当前项目实际代码，评估：

```text
Pandas
Polars
PyArrow
DuckDB
```

不要求一次全部替换。

---

# 74. Large Dataset Mode

当：

```text
rows > 100,000
```

进入：

```text
Large Dataset Mode
```

显示：

```text
300,000 rows detected

Analysis strategy:
optimized mode
```

---

# 75. 异步任务

不要：

```text
HTTP request
    ↓
等待长时间计算
```

改为：

```text
Job Queue
    ↓
Create Job
    ↓
Background Worker
    ↓
Progress
    ↓
Result
```

状态：

```text
QUEUED
RUNNING
COMPLETED
FAILED
CANCELLED
```

---

# 76. 分析进度

例如：

```text
Data loading          100%
Quality analysis      100%
Leakage detection      70%
Statistical analysis   20%
Modeling                0%
```

---

# 77. 第十六阶段：可重复研究

每次分析生成：

```text
Analysis ID
```

保存：

```text
dataset metadata
analysis configuration
software version
model version
random seed
analysis timestamp
```

---

# 78. Analysis Manifest

建议：

```json
{
  "dataset_hash": "...",
  "analysis_version": "2.0.0",
  "random_seed": 42,
  "validation": "StratifiedKFold",
  "folds": 5,
  "target": "month_group",
  "excluded_variables": [],
  "model_parameters": {}
}
```

---

# 79. 第十七阶段：医学数据安全

医学数据可能包含：

```text
PHI
PII
patient_id
name
phone
address
身份证
medical record number
```

优先：

```text
Local Analysis
+
Local Ollama
```

避免把原始患者数据发送给外部 API。

---

# 80. AI 脱敏层

发送给 LLM 前，尽可能只提供：

```text
Variable Metadata
Aggregated Statistics
Anonymized Examples
Analysis Results
```

而不是整个患者数据库。

---

# 81. 第十八阶段：Research Opportunity

分析结束后增加：

```text
Research Opportunities
```

展示：

```text
Observed Patterns
Unexpected Associations
Potential Subgroup Differences
Potential Prediction Tasks
Potential Hypotheses
```

统一标记：

```text
Hypothesis-generating
```

不得直接声称：

```text
Novel Finding
Guaranteed Publishable
```

---

# 82. 当前问题逐条修复优先级

## P0 — 必须首先完成

```text
P0-01 Target Leakage Detection
P0-02 Duplicate / Patient Leakage
P0-03 Prediction Time
P0-04 Data Quality Gate
P0-05 Perfect Performance Alert
P0-06 Correct CV Preprocessing
P0-07 Calibration
P0-08 PR-AUC
P0-09 Sensitivity / Specificity / PPV / NPV
P0-10 Analysis Status
P0-11 Sample Size / EPV Check
P0-12 Disclaimer & Scope of Use
```

---

## P1 — 第二优先级

```text
P1-01 Variable Dictionary
P1-02 Research Question Wizard
P1-03 Analysis Plan
P1-04 Subgroup Analysis
P1-05 Interaction Analysis
P1-06 Temporal Validation
P1-07 Group Validation
P1-08 Clinical Range
P1-09 Decision Curve Analysis
P1-10 Survival Analysis
P1-11 Missing Data Mechanism (MCAR/MAR/MNAR)
P1-12 Confounder Adjustment
P1-13 Multiple Comparisons Correction
P1-14 Continuous Outcome Metrics
P1-15 Statistical Engine Ground Truth Validation
```

---

## P2 — AI增强

```text
P2-01 Research Copilot
P2-02 Statistical Reviewer
P2-03 ML Reviewer
P2-04 Research Question Assistant
P2-05 Automated Report Writing
P2-06 Hypothesis Generation
P2-07 Evidence Binding
P2-08 AI Output Validator
```

---

## P3 — 平台化

```text
P3-01 Project Management
P3-02 Analysis History
P3-03 Reproducibility
P3-04 Dataset Versioning
P3-05 Analysis Manifest
P3-06 User Accounts
P3-07 Role Management
P3-08 Audit Log
```

---

# 83. 推荐实施顺序

不要一次性重写整个项目。

## Phase 0

```text
Repository Audit
Architecture Audit
Ollama/Qwen3.6 Audit
Technical Debt Analysis
```

---

## Phase 1

目标：

> 让系统首先“不会骗人”。

实现：

```text
Leakage Detection
Duplicate Detection
Patient-level Validation
Prediction Time
Data Quality Gate
Nested Preprocessing
Perfect AUC Alarm
Calibration
PR-AUC
Sensitivity
Specificity
PPV
NPV
```

---

## Phase 2

目标：

> 让医生知道自己正在做什么。

实现：

```text
Research Question
Study Design
Variable Dictionary
Prediction Time
Analysis Plan
```

---

## Phase 3

目标：

> 让模型评价达到临床研究级别。

实现：

```text
ROC
PR
Calibration
Threshold
DCA
Subgroup
Temporal Validation
```

---

## Phase 4

目标：

> 让 Qwen3.6 成为真正的 Research Copilot。

实现：

```text
OllamaProvider
ContextBuilder
ResearchPlanner
DataReviewer
StatisticalReviewer
MLReviewer
ReportWriter
AI Validator
```

---

## Phase 5

目标：

> 让报告成为研究工作底稿。

---

## Phase 6

目标：

> 支持 300,000+ 行数据研究项目。

---

# 84. Vibe Coding 开发规则

每个 Phase 必须遵循：

```text
Inspect
    ↓
Plan
    ↓
Implement
    ↓
Test
    ↓
Validate
    ↓
Document
```

每一个 Task 都必须明确：

```text
Task
Acceptance Criteria
Test Case
Expected Result
```

---

# 85. 禁止的开发方式

禁止：

```text
“把整个项目重构一下”
```

禁止：

```text
“把 AI 能力全部加进去”
```

禁止：

```text
“优化一下 UI”
```

必须拆成可执行任务。

---

# 86. Regression Dataset

至少准备：

```text
Dataset A:
正常二分类

Dataset B:
严重类别不平衡

Dataset C:
Target leakage

Dataset D:
Patient duplicates

Dataset E:
Extreme outliers

Dataset F:
Temporal data

Dataset G:
Survival data

Dataset H:
300k large dataset

Dataset I:
Ground truth simulated dataset
（已知真实效应量，用于验证统计引擎正确性，详见第 87 节）

Dataset J:
Low EPV dataset
（事件数极少、预测变量偏多，用于验证 Sample Size / EPV Check）
```

---

# 87. 统计引擎正确性验证 / Ground Truth Validation

第 80 节的 Regression Dataset A–H 用于验证系统"能否发现已知问题"（leakage、重复、不平衡等）。但目前没有机制验证系统计算出的统计量本身是否正确。Principle 1 要求"确定性引擎负责所有数值"，这不仅要求不用 LLM 计算，还要求引擎本身必须被证明是正确的。

## 新增

```text
Dataset I:
Ground Truth Simulated Dataset
```

使用已知真实效应量（true OR / true HR / true regression coefficients）模拟生成的数据集。

## 验证方式

```text
系统输出
    OR / HR / CI / p-value / AUC / Calibration Slope
        ↓ 对比
参考实现
    R: survival / glm
    Python: statsmodels / lifelines / scikit-learn
```

设定容差阈值（如相对误差 < 1%），纳入 CI 回归测试。

## 与第 80–81 节的关系

两者互补：

```text
第 80–81 节回归测试 → 验证 engine 是否"诚实"（能发现已知问题）
本节 Ground Truth 验证 → 验证 engine 是否"算得对"
```

两者都应作为 Definition of Done 的前置条件。

---

# 88. 当前 100,000 行数据作为回归测试

当前数据必须成为：

```text
Regression Test Dataset
```

每次重要升级都运行。

必须持续识别：

```text
age = 598

17,509 duplicate rows

3.5% positive class

month_group potential leakage

date/month related leakage
```

同时：

```text
AUC = 1.0
```

必须触发：

```text
Performance Integrity Check
```

而不是简单输出：

```text
Excellent Model
```

---

# 89. Phase 1 验收标准

使用当前 100,000 行数据。

必须识别：

```text
age = 598
17,509 duplicate rows
3.5% positive class
month_group potential leakage
date/month related leakage
```

如果模型：

```text
AUC = 1.0
```

必须显示：

```text
Critical methodological review required.
```

---

# 90. 最终产品架构

```text
                    Clinical Researcher
                           │
                           ▼
                ┌─────────────────────┐
                │ Research Copilot    │
                │ Qwen3.6 / Ollama    │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ Research Planner    │
                └──────────┬──────────┘
                           │
             ┌─────────────▼──────────────┐
             │ Clinical Analysis Engine   │
             ├────────────────────────────┤
             │ Data Quality               │
             │ Leakage Detection          │
             │ Statistics                 │
             │ Regression                 │
             │ Survival                   │
             │ Machine Learning           │
             │ Calibration                │
             │ Validation                 │
             └─────────────┬──────────────┘
                           │
                ┌──────────▼──────────┐
                │ Evidence Layer      │
                │ Analysis Results    │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ Research Report     │
                └─────────────────────┘
```

---

# 91. V2.0 核心原则总结

```text
1. AI解释结果，不制造结果。

2. Statistical Engine负责事实，
   LLM负责语言和推理辅助。

3. 数据质量问题优先于模型性能。

4. Leakage检查优先于模型排名。

5. Calibration不能被AUC替代。

6. Association不能自动解释成causality。

7. Predictive performance不能自动解释成clinical utility。

8. Exploratory findings不能自动解释成confirmed findings。

9. 医学异常值不能简单等同于统计异常值。

10. 研究者拥有最终确认权。
```

---

# 92. 最终产品目标

不要以：

```text
支持多少模型
```

作为核心 KPI。

应该关注：

```text
① 能发现多少严重数据问题

② 能阻止多少错误分析结论

③ 能否正确选择验证方法

④ 能否让研究人员理解分析结果

⑤ 能否形成可重复的研究分析过程
```

---

# 93. 给 Vibe Coding Agent 的最高级执行指令

```text
You are upgrading an existing Clinical Data Analysis Platform.

Do NOT rewrite the entire project blindly.

First inspect the existing repository and understand:

1. architecture
2. frontend
3. backend
4. data pipeline
5. statistical pipeline
6. machine learning pipeline
7. report generation
8. current Ollama integration
9. current Qwen3.6 integration
10. current tests

The primary objective of V2.0 is NOT to add more machine-learning models.

The primary objective is to make the platform scientifically safer and more useful for clinical researchers.

Prioritize:

1. Data quality
2. Target leakage detection
3. Patient-level leakage detection
4. Temporal leakage detection
5. Prediction-time validity
6. Correct cross-validation preprocessing
7. Calibration
8. PR-AUC for imbalanced outcomes
9. Sensitivity / specificity / PPV / NPV
10. Clinical interpretation
11. Research-question definition
12. Reproducibility
13. Sample size / EPV adequacy
14. Missing data mechanism assessment
15. Confounder-adjusted association analysis
16. Multiple comparisons correction
17. Continuous-outcome evaluation metrics
18. Statistical engine ground-truth validation

Use deterministic statistical code for:

- numerical calculations
- statistical tests
- model training
- validation
- metrics
- leakage detection
- data quality detection

Use Qwen3.6 through Ollama for:

- natural-language understanding
- research-question assistance
- variable semantic interpretation
- statistical-method explanation
- methodological review
- research-result explanation
- report generation

Never allow the LLM to invent or modify numerical results.

Every AI-generated claim must be traceable to structured analysis evidence.

If the system detects:

- AUC >= 0.99
- suspicious target correlation
- duplicate leakage
- patient leakage
- temporal leakage
- impossible clinical values
- severe missingness
- invalid validation design
- insufficient events per variable (EPV)
- likely MNAR missingness pattern

it must trigger a methodological warning or blocking gate before presenting model performance as trustworthy.

The existing 100,000-row dataset and its discovered issues must become regression-test cases.

Known regression issues include:

- target month_group
- positive rate around 3.5%
- age value 598
- 17,509 exact duplicate rows
- suspicious variables including month, Month, date_group, Year, seasons, Jieqi and date
- AUC = 1.0 in multiple models
- low events-per-variable ratio given ~3.5% positive rate (EPV check must also flag this dataset independently of leakage)

The new system must detect these issues automatically.

Do not remove problematic data silently.

Do not automatically treat statistical outliers as clinical errors.

Do not interpret statistical association as causation.

Do not interpret high AUC as clinical utility.

Do not impute missing data silently without first assessing the missingness mechanism.

Do not report unadjusted univariate p-values from batch testing without multiplicity correction.

Do not rank models as "winner" or "best model".

Instead present model candidates with:

- performance
- uncertainty
- validation method
- calibration
- methodological risks

Implement the upgrade incrementally.

For every phase:

1. inspect existing implementation
2. create implementation plan
3. modify code
4. run unit tests
5. run integration tests
6. run regression dataset
7. verify previous functions still work
8. document changes

Do not proceed to the next major phase until the current phase passes its acceptance criteria.

The final product should become a Clinical Research Data Analysis Copilot rather than a generic AutoML application.
```

---

# 94. 第一条实际开发任务

Vibe Coding Agent 第一次执行时，只执行：

```text
PHASE 0 — REPOSITORY AUDIT
```

不要立即修改代码。

最终必须先输出：

```text
1. Current Architecture
2. Existing Modules
3. Existing Analysis Pipeline
4. Existing Ollama/Qwen3.6 Integration
5. Existing Report Pipeline
6. Existing Tests
7. Technical Debt
8. Statistical Methodology Gaps
9. Medical Research Workflow Gaps
10. V2.0 Implementation Roadmap
11. Recommended File-level Changes
12. Risks of Refactoring
```

然后等待确认后再进入 P0。

---

# 95. V2.0 Definition of Done

只有以下条件全部满足，才能认为 V2.0 基本完成：

```text
✓ 100k 数据稳定运行
✓ 300k 数据能够运行
✓ 数据质量检查完善
✓ Target leakage 能够识别
✓ Patient leakage 能够识别
✓ Temporal leakage 能够识别
✓ Prediction Time 能够定义
✓ CV preprocessing 无明显 leakage
✓ Calibration 已实现
✓ PR-AUC 已实现
✓ Sensitivity / Specificity / PPV / NPV 已实现
✓ Research Question workflow 已实现
✓ Variable Dictionary 已实现
✓ Analysis Plan 已实现
✓ Subgroup analysis 已实现
✓ Temporal / Group validation 已实现
✓ Qwen3.6 / Ollama Copilot 已实现
✓ AI Evidence Binding 已实现
✓ AI Output Validator 已实现
✓ Report 已重新设计
✓ Regression Dataset 已建立
✓ Analysis Manifest 已建立
✓ Sample Size / EPV Check 已实现
✓ Missing Data Mechanism 判断已实现
✓ Confounder Adjustment 分析已实现
✓ Multiple Comparisons Correction 已实现
✓ Continuous Outcome Metrics 已实现
✓ Statistical Engine Ground Truth Validation 已通过
✓ Disclaimer 已在报告与 UI 中固定展示
✓ AI 不可用时核心分析仍可运行
✓ 严重方法学问题能够阻止或警告错误结论
```

---

# 96. 最终产品理念

这个项目最终不应该只是：

```text
Excel
 ↓
AutoML
 ↓
AUC
 ↓
Report
```

而应该变成：

```text
Clinical Data
      ↓
Understand
      ↓
Check
      ↓
Question
      ↓
Design
      ↓
Analyze
      ↓
Validate
      ↓
Challenge
      ↓
Interpret
      ↓
Report
```

核心竞争力不是“模型更多”。

而是：

> **帮助医学研究者减少错误分析、发现数据问题、理解统计结果，并把一次数据分析转化为一个可重复、可审查、可继续迭代的临床研究工作流。**
