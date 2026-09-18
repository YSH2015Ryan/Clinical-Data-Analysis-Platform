# V2 Gap Analysis

## P0 Matrix

| ID | 目标 | 当前状态 | 缺口 | 主要落点 | 验收证据 |
|---|---|---|---|---|---|
| P0-01 | Target leakage | 无独立执行引擎 | 目标复制、代理变量、目标命名/高度关联列需确定性 finding | `engines/leakage.py`, analysis worker | 合成 target/proxy fixture 能发现并显示证据 |
| P0-02 | Duplicate / patient leakage | 只有重复行 warning | patient/group 识别、跨 fold 组隔离、重复级别报告 | leakage + pipeline | 同一 patient 不跨 fold；重复行数准确 |
| P0-03 | Prediction time | DSL 无 prediction-time 契约 | 需要 time-zero、可用时间列、变量时间审计 | preprocessing schema + leakage | 缺少时间定义时 warning/block；未来变量被识别 |
| P0-04 | Data Quality Gate | QualityReport 独立存在 | 建模前统一 gate，阻断严重方法学风险并记录确认 | service/worker/schema | blocker 不可静默启动，warning 可审计确认 |
| P0-05 | Perfect performance | 报告有 EPV + AUC 红旗 | 应在 run integrity 中产生，列出组合风险 | leakage/integrity/report | AUC≈1 与低 EPV 显示 Critical methodological review required |
| P0-06 | Correct CV preprocessing | fold 内 Pipeline 基本正确 | group/time split、采样和特征选择审计 | pipeline/worker | 统计量只来自训练折；患者不跨折 |
| P0-07 | Calibration | 存在局部校准代码 | 明确 calibration curve/slope/intercept/Brier 产物及报告 | metrics/plugins/report | 真实预测对拍 sklearn |
| P0-08 | PR-AUC | 已有 average_precision_score | 统一字段、折级聚合、前端/报告展示和不平衡声明 | metrics/charts/report | 3.5% positive fixture 有 PR-AUC |
| P0-09 | Sens/Spec/PPV/NPV | 仅部分辅助代码 | 统一二分类指标字段和零分母语义 | metrics/report | 与 confusion_matrix 官方实现对拍 |
| P0-10 | Analysis status | 基础状态机存在 | gate/integrity/report provenance 状态可见 | ORM/schema/API/UI | API 和 UI 明确 BLOCKED/WARNING/COMPLETED |
| P0-11 | Sample size/EPV | EDA 粗略 EPV | 按候选变量、事件数和阈值统一计算 | data_quality_gate/EDA/report | low EPV fixture 得到 warning/critical |
| P0-12 | Disclaimer/scope | 固定免责声明已有 | 明确 internal CV、非临床用途、非因果、需外部验证 | report context/template/UI | HTML/PDF/UI 固定展示且测试覆盖 |

## Cross-Cutting Acceptance
- 所有数值由 deterministic engines 计算；LLM 不得产生或修改数值。
- 严重方法学问题不能被模板报告掩盖；报告必须带 gate/integrity/provenance。
- 同一 capability 必须有 engine test、worker/service wiring test、report/API contract evidence。
- 合成回归数据集覆盖正常、不平衡、target leakage、patient duplicate、outlier、temporal、survival、large、ground truth、low EPV。
- 100k 与 300k 验证必须记录原始样本、采样样本、阳性/事件保留量和运行状态。

## Deferred Beyond P0
研究问题向导、变量字典、分析计划、亚组、混杂调整、多重比较、外部验证和完整 OpenAPI 生成链属于后续计划项；P0 实现必须保留扩展字段，不以伪实现宣称完成。
