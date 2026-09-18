# 19. 测试计划（Test Plan）

## 1. 测试金字塔

```
        ┌────────────┐
        │  E2E (3 场景) │  ~5 用例
        ├──────────────┤
        │ 集成/API/契约  │  ~60 用例
        ├────────────────┤
        │   单元测试       │ 引擎层为主，覆盖率 ≥80%
        └────────────────┘
```

## 2. 单元测试

| 范围 | 重点用例 |
|---|---|
| engines/validation | 13 规则正反例（目录见 05 章 §3）；编码嗅探（UTF-8/GBK/GB18030/BOM）；阻塞/警告分级 |
| engines/preprocessing | 每步骤边界（全缺失列/单值列/未知类别/无穷值）；derive 沙箱拒绝 `__import__`；泄漏断言（scaler 均值仅来自 train fold）；同 config 双跑逐位相等 |
| engines/task_detection | 4 任务类型 × 词典内列名；歧义列（time 无 event）；失败回退 |
| engines/modeling | 适配器协议符合性（hypothesis 契约）；统一 metrics 与官方库对拍（C-index vs sksurv、AUC vs sklearn，±1e-6） |
| engines/comparison | 排名规则（构造指标断言顺序）；推荐理由快照测试（不虚构数值） |
| engines/ground_truth（updateplan §87，P1-15） | Dataset I 已知真实效应量模拟：OR/HR/β 收敛到真值且 95%CI 覆盖；与参考实现 statsmodels/lifelines 对拍相对误差 <1%；AUC 手算对拍（0.75/1.0/0.5）、校准斜率收敛到已知真值 0.5；§86 Dataset A–J 骨架性质冒烟（不平衡率/重复数/泄漏列/EPV） |
| engines/reporting | 模板渲染（缺章节「不适用」）；免责声明强制存在 |
| services | RBAC 过滤、存储抽象双实现一致性 |

工具：pytest + pytest-asyncio + hypothesis（属性测试用于解析器/DSL）。

## 3. 集成测试（testcontainers：PG + Redis + MinIO）

| ID | 场景 | 断言 |
|---|---|---|
| IT-01 | 上传→校验（好数据） | status=VALIDATED，报告无 blocker |
| IT-02 | 上传→校验（坏数据，缺结局列） | FAILED + RV101 阻塞 + 建议文本 |
| IT-03 | Quick Fix → 新版本 | 新版本存在，原文件 hash 未变 |
| IT-04 | 全链路生存分析 | chain+chord 完成，5 模型 SUCCESS，comparison 生成，状态 COMPLETED |
| IT-05 | 单模型故障注入（mock 抛异常/超时） | 该模型 FAILED 含 error，其余 SUCCESS，run 仍 COMPLETED |
| IT-06 | 取消运行 | revoke 生效，状态 CANCELED |
| IT-07 | worker kill -9 后 | janitor 标记 FAILED，可重试 |
| IT-08 | 报告生成 | PDF 存在且 >100KB，HTML 含全部章节锚点 |
| IT-09 | 越权访问 | 他人项目 run/dataset 全部 404/403 |
| IT-10 | 幂等 | 重复提交同 config 返回 409；重复 model_task 不产生重复行（UNIQUE） |

## 4. 契约与 API 测试

- **schemathesis**：基于 `/openapi.json` 模糊测试全部端点（CI 每夜跑）。
- 前端契约：comparison 响应字段同时被前端表格与报告模板消费——共享 JSON Schema 断言。

## 5. 金标准回归（Golden Dataset）

- 固定 3 份数据（合成生存/分类/回归 + 真实长表样本脱敏版）+ 固定 config。
- 真实数据来源：`D:\diseaseDB\mysql\{训练,测试,验证}集\样本集*\`（化验.csv 长表 + 诊断.csv，已预切分）。取训练集·样本集1 子集（≤1 万患者）经脱敏（患者ID 重哈希 + 日期统一偏移）后放入 `tests/fixtures/`，同时覆盖 reshape 长转宽路径；原始 6.2GB 数据**永不入库**，仅本地使用。
- CI 记录基线指标 JSON；科学栈依赖升级 PR 必须重跑并在阈值内（主指标差 < 1e-3）才允许合并。

## 6. 性能测试（locust + 计时脚本）

| 场景 | 指标 | 目标 |
|---|---|---|
| 10w 行 × 50 列全链路 | 端到端时长 | ≤ 10 min（4C8G） |
| 校验 | 时长 | ≤ 30s |
| PDF 生成 | 时长 | ≤ 60s |
| 上传 100MB | API 不阻塞 | p95 首响应 < 2s（异步） |
| 并发 10 用户各跑 1 分析 | 队列正常消化，无 OOM | worker RSS < 2GB |

## 7. 安全测试

- 上传：伪装扩展名/magic bytes、zip slip（不适用但检查路径穿越）、超大文件。
- 注入：derive 表达式沙箱、SQLAlchemy 参数化（审计 raw SQL 为零）。
- 越权：自动化 403/404 矩阵（用户×角色×资源）。
- 依赖：CI `pip-audit`；许可证 `pip-licenses`。

## 8. 前端测试

- 组件：Testing Library（QualityReportPanel 分级渲染、向导步骤流转）。
- E2E：Playwright 跑 01 章场景 A/B/C（CI  nightly，本地 compose 环境）。

## 9. 覆盖率门槛

| 层 | 门槛 |
|---|---|
| engines/* | ≥ 85% |
| services/* | ≥ 80% |
| api/* | ≥ 70% |
| 整体后端 | ≥ 80%（CI 强制，低于则失败） |
