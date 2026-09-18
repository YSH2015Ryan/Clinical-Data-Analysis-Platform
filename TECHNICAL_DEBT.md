# Technical Debt

以下债务来自 P0 升级前审计，按对研究结论真实性的风险排序。

## Critical
- Target leakage、代理结局、重复患者、时间泄漏尚未形成统一确定性检查和阻断/确认机制。
- 随机 KFold 可能把同一患者或重复记录分到 train/validation 两侧。
- Prediction time 没有成为配置契约，无法系统判断某个变量在预测时点是否已可获得。
- 数据质量报告与建模 gate 分离，严重重复、临床不合理值、低 EPV 和极端不平衡不一定阻止建模。
- >100k 采样不是结局/患者/时间感知采样。

## High
- EPV 使用第一个 Event/Label 语义列和粗略特征数，未按任务、group、编码后维度或候选预测变量计算。
- `time_series` 只在 schema/DB 声明，执行链路没有完整实现。
- 分类指标虽有部分实现，但 sensitivity/specificity/PPV/NPV 的标准字段、折级聚合、报告展示未统一。
- 校准产物存在于模型/报告辅助代码，但没有成为明确的分析完整性检查。
- 完美 AUC 红旗仅在报告阶段按 EPV 组合触发，不能在模型运行前提示泄漏或低 EPV。
- 报告解释失败可能降级为模板而不充分暴露 provenance。

## Medium
- Ollama 通用 `complete` 存在同步/异步协议不一致风险。
- 前端存在手写 API DTO，尚未完全从 OpenAPI 生成。
- CI 没有 Redis/MinIO/Celery chord、前端 build、Playwright、Schemathesis 和 golden dataset 门禁。
- coverage 配置与升级计划要求不一致，核心 workers/plugins 的覆盖不足。
- 报告下载一次性读入 bytes，生产大报告会增加内存压力。

## Resolution Policy
债务不得通过删除功能或静默放宽校验解决。P0 优先完成方法学安全边界，再处理可运维性和契约自动化。任何新 gate 必须提供：finding、severity、evidence、recommended_action、override/confirmation 语义和测试。
