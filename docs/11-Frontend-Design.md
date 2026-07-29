# 11. 前端设计（Frontend Design）

> React 18 + TypeScript + Vite + Ant Design 5 + ECharts + Zustand + React Router + openapi-typescript 生成客户端。

## 1. 页面地图

```mermaid
flowchart TD
    L[/login 登录/] --> P[/projects 项目列表/]
    P --> PD[/projects/:id 项目工作台/]
    PD --> UP[上传数据集<br/>UploadZone]
    PD --> DS[/datasets/:id 数据集详情/]
    DS --> QR[质量报告视图]
    DS --> QF[在线修复]
    PD --> WZ[/analysis/new 分析向导/]
    WZ --> W1[Step1 选择数据集]
    WZ --> W2[Step2 预处理配置<br/>推荐默认值]
    WZ --> W3[Step3 任务类型确认<br/>自动推荐+理由]
    WZ --> W4[Step4 选择模型<br/>默认全选]
    WZ --> W5[Step5 确认并提交]
    PD --> RS[/runs/:id 运行监控/]
    RS --> RES[/runs/:id/results 结果与比较/]
    RES --> RP[/reports/:id 报告预览/]
    AD[/admin 管理<br/>用户/模型插件/审计/]
```

## 2. 关键页面设计

### 2.1 上传与质量报告

- `UploadZone`：拖拽 + 批量 + 进度条；>50MB 分片（P2）。
- 上传完成自动跳转质量报告页：
  - 顶部：状态横幅（绿色通过 / 黄色 N 个警告 / 红色 N 个阻塞，阻塞时「开始分析」按钮禁用）
  - 中部：问题清单表格（级别/列/问题/影响行数/建议/一键修复按钮）
  - 底部：列画像（每列类型、缺失率、分布迷你图）
- 一键修复弹出影响预览（「将删除 521 行中的 12 行重复记录」）→ 确认生成新版本。

### 2.2 分析向导（核心体验）

| 步骤 | 内容 | 默认值策略 |
|---|---|---|
| 1 数据集 | 选择项目内已校验数据集 | 最近使用 |
| 2 预处理 | 步骤开关 + 参数（手风琴面板） | 「推荐配置」已填充，可整体重置 |
| 3 任务类型 | 卡片式展示推荐结果 + 置信度 + 理由，可切换 | 自动推荐项默认选中 |
| 4 模型 | 按任务类型过滤的模型多选，标注预计耗时 | 全选 |
| 5 确认 | 全参数摘要 + 预计总耗时 → 提交 | — |

### 2.3 运行监控

- 轮询 `/progress`（2s 间隔）或 SSE。
- 可视化：总进度条 + 每模型状态芯片（排队/运行/成功/失败 + 失败原因 tooltip）。
- 操作：取消、失败后重试。

### 2.4 结果与比较页

- Tab1 性能表：可排序表格，Top3 奖牌标注 + 推荐理由卡片。
- Tab2 图表：ROC 叠加/校准/DCA/混淆矩阵/KM（ECharts，工具箱支持导出 PNG）。
- Tab3 可解释性：SHAP 摘要、特征重要性、HR 森林图。
- Tab4 各模型详情：每模型指标 + 失败模型的错误信息 + 「重跑此模型」。
- 顶部固定操作：「生成报告」→ 选格式/模板 → 跳转报告预览。

### 2.5 报告页

- iframe HTML 预览（sandbox）+ 下载按钮（PDF/HTML）。
- 历史报告列表（同 run 多版本）。

## 3. 组件清单

| 组件 | 职责 |
|---|---|
| UploadZone | 拖拽/批量/进度 |
| QualityReportPanel | issues 表格 + 画像 + QuickFix |
| ColumnProfileGrid | 列画像卡片 |
| PreprocessConfigurator | DSL 可视化编辑（受控表单，输出 JSON） |
| TaskTypeRecommender | 推荐卡片 + 置信度 + 覆盖 |
| ModelSelector | 模型多选 + 能力标签（SHAP/校准） |
| RunProgressBoard | 进度条 + 模型状态芯片 |
| MetricsTable | 性能表（排序/高亮 Top3） |
| ChartPanel | ECharts 封装（roc/dca/km/shap） |
| ReportViewer | iframe 预览 + 下载 |

## 4. 状态与 API 约定

- Zustand store：`useProjectStore / useRunStore`；服务端状态用 TanStack Query（缓存+轮询）。
- 所有 API 调用走 `openapi-typescript` 生成的类型化客户端；错误码统一 toast（错误码见 14 章）。
- 路由守卫：未登录 → /login；viewer 角色隐藏「提交分析/修复」按钮。

## 5. 交互与可用性要求

- 全中文文案；所有异步操作有 loading 与空状态。
- 点击到报告路径 ≤ 6 步（验收指标 G1）。
- 表单变更即校验（Pydantic schema 同源生成 zod schema，P2）。

## 6. DoD

- [ ] 三个验收场景（01 章场景 A/B/C）可完整走通
- [ ] 阻塞级问题正确禁用分析入口
- [ ] 结果页与报告数据一致（同一 API）
- [ ] Chrome/Edge 最新两版无控制台错误
