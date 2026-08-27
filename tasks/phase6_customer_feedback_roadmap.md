# Task: Phase 6 — 客户反馈整改路线图（2026-08-27 客户反馈驱动）

## 任务类型

路线规划文档（含 P0/P1/P2 全部任务拆解与 DoD）。实施时每个 Task 单独提 PR，遵循 CLAUDE.md 十条规范。

## 背景：客户反馈五问题

1. **校验报错不可操作**:阻塞报错多，客户看不懂、不会修，流失。
2. **任务识别偏向预测**:默认很少推荐回归；手动选回归后报告只有一张图+简单分析。
3. **LLM 未发挥价值**:已接入服务器端 Ollama 小模型（本地优先，可降级外部大模型）,但未参与"数据能做什么研究/用什么模型/能出什么图"的建议。
4. **定位升级**:要从"分析工具"提升到"科研数据助手"。
5. **慢、常失败、不专业**:模型评估慢、失败率高；模型数量多但分析结果不像期刊级产出。

## 核心诊断（2026-08-27 代码调研结论）

**主要矛盾不是缺功能，而是"建而未接"**——以下 4 个模块已完整开发且有测试，但业务流程零调用（全仓 grep 仅 tests 引用）:

| 模块 | 路径 | 应接入位置 |
|---|---|---|
| 校验富文案库（RV001–RV804，含原因+3种修法+一键操作） | `backend/app/engines/validation_messages.py` | `engines/validation.py` 产出 Issue 时按 rule_id 查表 |
| Table 1 基线表 | `backend/app/engines/reporting/baseline_table.py` | `engines/reporting/context.py` / `workers/report_tasks.py` |
| 效应量 + 回归诊断 | `backend/app/engines/reporting/effect_size.py`、`diagnostics.py` | 同上 |
| 模型间统计检验（Friedman/Wilcoxon/t) | `backend/app/engines/comparison/statistics.py` | 报告性能表 |

此外 `backend/app/services/llm.py` 完整实现（Ollama 本地优先 + OpenAI 降级 + 防幻觉校验）但零业务调用，且配置全部硬编码（`localhost:11434`、`qwen2.5:7b`),`config.py` 无任何 LLM 配置项，`init_llm_service()` 从未在启动时调用。

---

## P0 任务（两个迭代内，消灭 80% 客户抱怨）

### T6.1 校验报错可操作化

- **改动**:
  - `engines/validation.py`:Issue 增加 `row_indices`（采样式，如前 20 行）；产出时按 `rule_id` 关联 `validation_messages.py` 富文案（原因/方法1/2/3/一键操作）。
  - `api/v1/datasets.py` quality-report 响应 schema 同步扩展（**先走 docs/14 §5 变更流程**)。
  - 前端 `DatasetDetailPage.tsx:85-93` 删除硬编码 RV201/301/401 映射，改为消费通用富文案结构；"点击问题 → 高亮数据行"交互。
- **DoD**:任一阻塞报错展示"哪列哪几行+具体原因+至少 2 种修法+一键修复按钮（有对应 quick-fix 时）"；单测覆盖 rule_id→富文案映射与行号采样。

### T6.2 任务识别偏置修正

- **改动** `engines/task_detection.py`:
  - 0/1 列无语义命中时不再直接以 0.5 置信度定为二分类；增加守卫：数据集中存在更像结局的连续列（列名命中 label 词典/高方差/末列启发式）时回归优先。
  - 置信度 <0.6 的判定降级为候选列表，交由用户确认（detect-task API 已有 candidates 机制，前端需展示）。
- **DoD**:构造"含 0/1 标志列+连续结局"的回归数据集，识别结果为 regression;低置信度场景返回 candidates 而非单一结论；补对应失败测试先行。

### T6.3 回归/报告三模块接线

- **改动**:
  - `engines/reporting/context.py` + `workers/report_tasks.py`：回归任务报告装配 Table 1 基线表、系数/效应量表（β、95%CI、p)、诊断四图（残差/Q-Q/VIF/影响点）;分类/生存任务同步接入 baseline_table。
  - 模板 `clinical_report_zh.html.j2` 增加对应章节。
  - "临床解读"段落（`context.py:60-76`）改为从 effect_size 结果生成。
- **DoD**:回归任务报告至少含 基线表+效应量表+诊断图+预测散点；所有数字来自真实计算（红线8);PDF/HTML 双端渲染正常。

### T6.4 统计显著性进性能表

- **改动**:报告性能表接入 `comparison/statistics.py` 的 `add_pvalues_to_performance_table`(Friedman + 成对 Wilcoxon)；差异不显著时明确标注。
- **DoD**：报告性能表含 p 值列；推荐理由区分"显著优于"与"数值略高但差异不显著"。

### T6.5 训练性能与失败治理

- **改动** `workers/analysis_tasks.py` 及插件:
  - Celery `soft_time_limit` 按模型分档（替代仅靠 janitor 5 分钟轮询）。
  - 回归/生存插件补 `max_train_rows` 采样保护（对齐 classification.py:185-317 现有做法）。
  - 消除"K 折 CV + 全量 fit"双训练：fold 模型复用或解释性需要时再单独 fit。
  - `n_jobs=-1` 推广到所有支持的模型。
  - 失败原因分类化：裸异常（现 2000 字符截断）→ 分类（内存/超时/数据不适配/收敛失败）+ 用户可读提示 + 建议动作。
- **DoD**：单模型超时后 1 分钟内标记失败并给出分类原因；10 万行数据集回归任务不 OOM；失败信息用户可直接理解。

---

## P1 任务（LLM 接线，质变"智能感")

### T6.6 LLM 设置界面（前置依赖，P1 最先做）

**背景**:LLM 配置全部硬编码，无配置项、无状态接口、无界面。服务器端另有开发人员会调整代码与环境参数，必须提供图形化配置入口，避免改代码。

- **配置分层**:

| 层级 | 内容 | 存放 | 修改方 |
|---|---|---|---|
| 部署层 | Ollama 地址、是否启用云端、默认模型名 | 环境变量 / docker-compose | 服务器开发人员 |
| 运行层 | 模型策略（auto/local/cloud)、分功能开关、云端 key、温度 | DB `admin_settings` 表（key 加密存） | 管理员界面 |

- **改动**:
  - 后端：`admin_settings` 表（key-value + Fernet 加密字段）;`GET /settings/llm/status`（包装现成 `get_status()`)、`PUT /settings/llm`、`POST /settings/llm/test`（真实发最小请求测连通+延迟）;Ollama 模型列表代理 `/api/tags`;启动时从 DB 读配置调 `init_llm_service()`。**API 变更先走 docs/14 §5**。
  - 前端：管理员"AI 设置"页——Provider 状态卡片、连接测试按钮、Ollama 模型下拉（免手敲）、云端配置（key 只写不读，显示 `sk-****`)、分功能开关（研究画像/报告解读/校验解释 × 关闭/仅本地/本地优先/仅云端）、降级链说明文字。
  - 部署：docker-compose 增加 Ollama service（或挂宿主机）;`deploy/.env.example` 补 `OLLAMA_BASE_URL`、`OLLAMA_MODEL`、`LLM_DEFAULT_CHOICE` 等。
- **红线**：任何情况下不向云端 LLM 发送行级患者数据，只允许聚合统计 facts 与列元数据；cloud provider 入口强制校验 payload 结构；界面云端开关旁配合规说明文字（医疗机构采购门槛）。
- **DoD**：管理员不重启服务即可切换模型与策略；连接测试真实反映可用性；云端关闭时所有 LLM 功能自动回退本地/模板；key 不明文出现在任何 API 响应与日志中。

### T6.7 LLM 接线三处业务

按价值排序，均遵循"LLM 只做表达与推理增强，不做计算；所有数字必须来自引擎":

1. **研究画像增强**:`engines/research_profiler.py` 规则输出作为结构化上下文喂 LLM,生成"2–3 个可回答的研究问题 + 每个问题的设计/模型/图表建议";`llm_validators` 防幻觉，规则结果作 fallback。
2. **报告解读段落**：替代 `context.py` 模板拼句，用真实指标 + LLM 生成解读；validators 拦截编造数值。
3. **校验报错自然语言解释**:Issue + 富文案 → "人话版"修复指引（与 T6.1 衔接）。

- **DoD**:LLM 不可用时三处均自动回退现有规则/模板输出，主流程不阻塞；validators 单测覆盖幻觉数值拦截。

### T6.8 quick-fix 全覆盖

- 高发校验规则（缺失值/类型/异常值等）全部配一键修复，"报错→点一下→重验"成为主路径。

---

## P2 任务（科研助手代差）

- **T6.9 科研流程模板库**：预后模型/危险因素/剂量反应/纵向 四类研究模板 → 按模板自动配置任务+模型+图表；样本量与统计功效提示。
- **T6.10 单因素→多因素筛选流程 + 亚组分析**。
- **T6.11 报告对标期刊结构**:Table 1 → 方法 → 主结果表（效应量+CI+p)→ 诊断/校准 → 局限；STROBE/TRIPOD 清单自查；Word 导出。
- **T6.12 模型分层套餐**：每任务"标准套餐"3–5 个（基线+强模型+可解释模型），其余折叠为高级选项，取代堆量。
- **T6.13 对话式迭代**:LLM 回答"如果把 X 当协变量会怎样" → 生成重跑建议。
- **明确不做**：自动选题、自动写论文（违背红线8 结果真实）。

---

## 交接说明（致服务器端开发人员）

1. **你只动部署层**:docker-compose、`deploy/.env.example`、环境变量（Ollama 地址/模型名/是否启用云端）。运行层的模型策略与开关请引导管理员在"AI 设置"界面调整，不要改代码硬编码。
2. `backend/app/services/llm.py` 的 `LLMService.__init__` 参数将全部改为从"环境变量默认值 + DB 覆盖"注入（T6.6)，请不要再直接改默认值。
3. Ollama 与后端同机部署时注意 worker 容器内存配额：T6.5 的采样保护按模型分档，阈值在 `config.py` 集中管理，可调。
4. 所有 API 变更需同步 `docs/14-API-Specification.md`(§5 变更流程），前端类型只从 OpenAPI 生成物获取。
5. 每个 Task 单独 PR,Conventional Commits，关联本文档 Task 编号（如 `T6.3`)；引擎模块测试先行，覆盖率 engines ≥85%。

## 依赖与顺序

```
T6.1 ─┐
T6.2 ─┼─ P0 并行可拆
T6.3 ─┤
T6.4 ─┤
T6.5 ─┘
T6.6(LLM 设置)─→ T6.7(LLM 接线)─→ T6.8
P0 全部完成 + T6.6/6.7 ─→ P2(T6.9 起)
```
