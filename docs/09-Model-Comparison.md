# 09. 模型比较（Model Comparison）

> 模块 6。职责：把多个模型的结果汇总为**性能表 + 图表 + 自动排名与推荐理由**。引擎位于 `engines/comparison/`。

## 1. 模块卡片

| 项 | 内容 |
|---|---|
| 职责 | 汇总 ModelResult → 性能对比表 → 对比图表 → 排名推荐 |
| 输入 | run 的全部成功 ModelResult |
| 输出 | `Comparison`（ranking/recommendation/charts） |
| 依赖 | 统一 metrics 模块、Plotly（报告图）、matplotlib（PNG） |
| 复杂度 | 中 |
| 风险 | 指标口径不一致 → 指标统一在 metrics 模块（见 07 章）；排名规则须透明可解释 |

## 2. 性能对比表（前端表格 + 报告表格共用数据源）

分类任务示例：

| 模型 | AUC (mean±std) | Accuracy | Precision | Recall | F1 | Brier ↓ | 校准 | 耗时 |
|---|---|---|---|---|---|---|---|---|
| lightgbm | **0.873±0.021** | 0.81 | 0.79 | 0.77 | 0.78 | **0.121** | 优 | 42s |
| xgboost | 0.865±0.024 | 0.80 | 0.78 | 0.75 | 0.76 | 0.128 | 优 | 51s |
| catboost | 0.861±0.019 | 0.80 | 0.77 | 0.76 | 0.76 | 0.130 | 良 | 63s |
| rf | 0.842±0.027 | 0.78 | 0.75 | 0.74 | 0.74 | 0.141 | 良 | 38s |
| logreg | 0.811±0.022 | 0.75 | 0.73 | 0.72 | 0.72 | 0.152 | 优 | 3s |
| svm | 0.798±0.031 | 0.74 | 0.71 | 0.73 | 0.72 | 0.158 | 差 | 88s |

生存任务主指标为 C-index±std，辅以 IBS；回归为 RMSE。

## 3. 对比图表清单

| 图表 | 任务 | 实现 |
|---|---|---|
| ROC 多模型叠加 | classification | 数据 JSON（前端 ECharts）+ PNG（报告） |
| 校准曲线（reliability diagram） | classification/survival | sklearn calibration + 自绘 |
| 决策曲线 DCA | classification/survival | 自实现净获益公式（参考 dcurves 库算法，必要时引入该库） |
| 混淆矩阵 | classification | sklearn |
| KM 曲线（按风险分层） | survival | lifelines |
| C-index 森林图 | survival | 自绘 |
| 特征重要性对比（Top-N 并排） | 全部 | SHAP/importance 汇总 |
| HR 森林图（Cox） | survival | lifelines 系数 |

> **单数据源原则**：每图生成一次数据 JSON，前端交互图与报告静态图都由它渲染，避免两处不一致。

## 4. 自动排名与推荐

### 4.1 排名规则（透明、可解释）

```
score = 0.6 × 主指标(CV mean, 归一化)
      + 0.2 × 稳定性(1 - CV std 归一化)
      + 0.2 × 校准/拟合优度(任务相关次级指标)
```

- 主指标：classification=AUC、survival=C-index、regression=1/RMSE 归一。
- 规则权重存配置，报告中**完整披露排名公式**（可解释要求）。

### 4.2 推荐理由模板

```
Top1 {model}: 主指标最高({metric}={value}±{std})，校准误差低，交叉验证稳定。
Top2 {model}: 主指标接近 Top1({value})，可解释性强（系数/HR 可直接用于论文表格）。
Top3 {model}: 性能略低但训练最快，适合大样本快速迭代。
```

理由由模板引擎基于指标事实生成，**不虚构**；同时输出「不推荐 X 的原因」（如：校准差/过拟合迹象=训练-验证差距>0.1）。

## 5. 输出契约

`GET /analysis-runs/{id}/comparison` → 返回性能表 JSON、排名、理由、图表数据 uri 列表。前端结果页与报告引擎共用此响应。

## 6. DoD

- [ ] 三类任务各产出完整性能表 + 全部适用图表
- [ ] 排名规则单元测试：构造已知指标 → 断言排名顺序
- [ ] 推荐理由内容校验：只引用真实指标值（快照测试）
- [ ] 前端结果页与报告中的表格数据一致（同一 API 数据源，契约测试）
