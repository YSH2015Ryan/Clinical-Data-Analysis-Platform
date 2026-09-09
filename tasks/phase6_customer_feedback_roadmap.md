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

### T6.3 回归/报告三模块接线 ✅(2026-08-28 完成)

- **改动**:
  - `engines/reporting/context.py` + `workers/report_tasks.py`：回归任务报告装配 Table 1 基线表、OLS 系数表（β、95%CI、p)、诊断（Shapiro/BP/DW/VIF，基于 OOF 残差）;分类/生存任务同步接入 baseline_table；分类另接入 Hosmer-Lemeshow 校准 + Youden 最优阈值。
  - `workers/analysis_tasks.py`:OOF 预测持久化 `runs/{id}/oof_{model}.parquet`（诊断/校准数据源）。
  - 模板 `clinical_report_zh.html.j2` 增加基线表/系数表/诊断检验/VIF 块。
  - "临床解读"段落（`context.py`）追加诊断与校准的真实检验结论。
- **DoD**:回归任务报告至少含 基线表+效应量表+诊断图+预测散点；所有数字来自真实计算（红线8);PDF/HTML 双端渲染正常。
- **落地说明**：诊断四图中的残差/预测散点图已由 comparison charts（基于 OOF 产物）覆盖；Q-Q/影响点图并入后续 T6.11 期刊结构报告统一处理。

### T6.4 统计显著性进性能表 ✅(2026-08-28 完成)

- **改动**:报告性能表接入 `comparison/statistics.py` 的 `add_pvalues_to_performance_table`（折级配对 t 检验）；性能表按 ranking 排序，首行标"参考"，表下附方法学说明（`add_statistical_significance_note`)。
- **DoD**：报告性能表含 p 值列；推荐理由区分"显著优于"与"数值略高但差异不显著"。
- **遗留**:推荐理由文案区分显著性（需 ranking 引擎感知 p 值）并入 T6.11 一并处理。

### T6.5 训练性能与失败治理 ✅(2026-08-28 完成)

- **改动** `workers/analysis_tasks.py` 及插件:
  - Celery `soft_time_limit` 按模型分档（替代仅靠 janitor 5 分钟轮询）。
  - 回归/生存插件补 `max_train_rows` 采样保护（对齐 classification.py:185-317 现有做法）。
  - 消除"K 折 CV + 全量 fit"双训练：fold 模型复用或解释性需要时再单独 fit。
  - `n_jobs=-1` 推广到所有支持的模型。
  - 失败原因分类化：裸异常（现 2000 字符截断）→ 分类（内存/超时/数据不适配/收敛失败）+ 用户可读提示 + 建议动作。
- **DoD**：单模型超时后 1 分钟内标记失败并给出分类原因；10 万行数据集回归任务不 OOM；失败信息用户可直接理解。
- **落地**:
  - `engines/failure.py` 五类分类（timeout/memory/convergence/data/unknown）+ 建议文案，类名鸭子识别不依赖 celery；`plugins/builtin/sampling.py` 确定性分层采样（seed=42)。
  - 软限分档 default=480s/heavy=840s，使用时钳制 ≤ `MODEL_TIMEOUT_S−60s`;`config.py` 仅校验分档顺序（部署可调低硬超时）。
  - 生存插件 coxph/rsf/gbs 与回归 rf_reg/xgboost_reg 全部 `max_train_rows` 分层子采样；xgboost/lightgbm/catboost 吃满核。
  - 有 OOF 且无可解释性产物的模型跳过全量 fit（km 类直接由 OOF 生成 artifacts)。
- **顺带修复**（实施中暴露的存量 bug):
  - `ModelResult.updated_at` 缺失致 janitor 每次巡检即 AttributeError → 补列 + migration 0006;janitor PREPROCESSING/COMPARING 僵死判定回归 model_timeout_s(f66e668 误改为 run_timeout_s 破坏 T5.9 契约）。
  - LightGBM `min_child_samples=100` 在小数据严重欠拟合（AUC 0.57)→ 仅 ≥1 万行启用；实体 DateTime 列全部显式 `timezone=True` 对齐 DDL(create_all 测试库与 aware 比较崩溃）。
- **测试**:`test_analysis_resilience.py` 20 例（分类/分档/签名/采样/跳过/n_jobs);lifecycle+config+adapters+orchestration+report_wiring 共 190+ 例全绿。

---

## P1 任务（LLM 接线，质变"智能感")

### T6.6 LLM 设置界面（前置依赖，P1 最先做）✅(2026-08-28 完成)

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
- **落地**（端点按 docs/14 §5 定稿为 `/admin/settings/llm*` 前缀，与既有 /admin/plugins 对齐）:
  - `admin_settings` 表（migration 0007)+ `services/settings.py`(Fernet,dev 由 JWT_SECRET 派生密钥，prod 必须显式 `SETTINGS_ENCRYPTION_KEY`,config fail-fast);
  - `GET/PUT /admin/settings/llm`、`POST .../test`、`GET .../ollama-models`;PUT 后 `init_llm_service_from_runtime` 热更新；启动 lifespan 从 DB 注入；
  - 隐私守卫 `services/llm_privacy.py`:cloud 入口强制校验（禁用键/集合长度/体积）,`LLMService.cloud_enabled` 部署层总闸；
  - 前端 `/admin/ai-settings` 页 + 项目页入口按钮；compose `ollama` service(profile=llm）与 `.env.example` 部署层键。
- **测试**:`test_llm_settings.py` 22 例（加密往返/合并/掩码/无明文泄露/审计不含值/admin 门控/test 端点 mock 传输层/总闸拒绝/守卫拦截）。
- **遗留**:`test_llm_service.py::TestOutputValidator::test_validate_format_with_numbers` 为存量失败（干净 HEAD 复现，与 T6.6 无关），校验器阈值调优并入 T6.7。

### T6.7 LLM 接线三处业务

按价值排序，均遵循"LLM 只做表达与推理增强，不做计算；所有数字必须来自引擎":

1. **研究画像增强**:`engines/research_profiler.py` 规则输出作为结构化上下文喂 LLM,生成"2–3 个可回答的研究问题 + 每个问题的设计/模型/图表建议";`llm_validators` 防幻觉，规则结果作 fallback。
2. **报告解读段落**：替代 `context.py` 模板拼句，用真实指标 + LLM 生成解读；validators 拦截编造数值。
3. **校验报错自然语言解释**:Issue + 富文案 → "人话版"修复指引（与 T6.1 衔接）。

- **DoD**:LLM 不可用时三处均自动回退现有规则/模板输出，主流程不阻塞；validators 单测覆盖幻觉数值拦截。✅
- **落地**（三处均经 T6.6 分功能开关门控 off/local/local_first/cloud，关闭或 LLM 失败自动回退）:
  - 研究画像：`services/llm_tasks.py::generate_research_questions`,facts=规则画像+行列数+列名（≤50),JSON 解析+模型/图表白名单过滤+逐条幻觉拦截，接线 `api/v1/datasets.py::get_research_profile`(to_thread 防阻塞事件循环）;
  - 报告解读：`workers/report_tasks.py::_llm_interpretations` 装配三章节 facts（真实 payload 值组装，`citable_numbers` 把结论字符串内数值注入 facts 防误杀）,`context.py`/模板渲染 `llm_paragraph`，模板拼句兜底；
  - 校验解释：`workers/dataset_tasks.py::_explain_blockers` 为阻塞级 Issue 生成 ≤5 条通俗解释（`llm_explanation` 字段，长度+幻觉双重校验）;
  - `settings.py` 补 sync 读配置（Celery worker 用）;`OllamaProvider/OpenAIProvider.complete()` 通用补全接口；
  - 校验器阈值调优：最短 100→80，分点关键词收窄为 首先|其次|最后（修复 T6.6 遗留存量失败 `test_validate_format_with_numbers`);
  - docs/14 补录 `POST /datasets/{id}/research-profile` 契约 + `research_questions`/`llm_explanation` 字段（变更记录 2026-08-27 ×2)。
- **测试**:`test_llm_wiring.py` 22 例（开关映射/三站点幻觉拦截/失败回退/报告 facts 装配/诊断截断/sync 接线）+ `test_llm_service.py` 25 例（含 80 字边界、分点词仍拦截）+ API/context/settings/report wiring 套件，合计 96 例全绿；ruff/mypy 改动文件全净。

### T6.8 quick-fix 全覆盖

- 高发校验规则（缺失值/类型/异常值等）全部配一键修复，"报错→点一下→重验"成为主路径。

---

## P2 任务（科研助手代差）

- **T6.9 科研流程模板库**：预后模型/危险因素/剂量反应/纵向 四类研究模板 → 按模板自动配置任务+模型+图表；样本量与统计功效提示。✅
  - **落地**:`engines/research_templates.py`（纯引擎，列检测复用 research_profiler）按数据集真实统计评估四模板适用性（任务类型/模型/图表随数据动态选择）；样本量经验规则核对：EPV≥10(logistic/Cox)、n/p≥20（回归）、纵向 n≥50,数值全部真实计算（红线8);`GET /datasets/{id}/research-templates`(docs/14 §5 变更记录 2026-08-27)；前端分析向导 Step 1 模板卡片，"使用此模板"预填任务类型+推荐模型（后续步骤可改）。
  - **测试**:`test_research_templates.py` 19 例（四模板适用性/EPV/n/p 真实数值/阈值上下界/空表不崩/hints 尊重）+ `test_research_templates_api.py` 4 例（结构/队列适用/404/401);ruff/mypy 改动文件全净，前端 tsc 净。
- **T6.10 单因素→多因素筛选流程 + 亚组分析**。✅
  - **落地**:`engines/screening.py`（纯引擎；scipy/statsmodels/lifelines 真实计算）——单因素筛选：分类=Mann-Whitney/Fisher(2x2)/卡方+Cramér's V，生存=单因素 Cox(多水平走整体 LRT)，回归=Pearson 相关/单因素方差分析+η²,p<alpha 入选（特征上限 50)；亚组分析：分层暴露效应 OR(log 法 CI，零格 0.5 校正）/HR(Cox)/β(OLS) + 暴露×亚组交互 LRT p(Logit/OLS/Cox 全模型 vs 无交互），亚组水平 2-6、每层 n<10 给 note 不虚构。端点 `POST /datasets/{id}/univariate-screen`、`POST /datasets/{id}/subgroup-analysis`(docs/14 §5 变更记录 2026-08-27)；前端数据集详情页「科研助手」卡（ScreeningCard)：筛选结果表（按 p 升序、入选标绿）+ 亚组效应表（效应 95%CI + 交互 p 判读）。
  - **测试**:`test_screening.py` 14 例（三任务类型/真实 p 与效应方向/α 阈值/特征上限/交互 p 范围/非法输入）+ `test_screening_api.py` 6 例（结构/400/404/401);ruff/mypy 改动文件全净，前端 tsc 净。
- **T6.11 报告对标期刊结构**:Table 1 → 方法 → 主结果表（效应量+CI+p)→ 诊断/校准 → 局限；STROBE/TRIPOD 清单自查；Word 导出。✅
  - **落地**:`engines/reporting/checklist.py`（纯引擎）——TRIPOD+STROBE 10 条目自查（样本量/结局事件数/EPV≥10/内部验证/候选模型/区分度指标/不确定性度量/校准度/缺失值处理/可复现性），状态 满足/部分满足/待补充/不适用，依据字符串含 payload 真实数值（红线8)；报告章节顺序调整为 …→ 局限 → 报告规范自查 → 结论（期刊结构，SECTION_TITLES 9/10/11 顺延）;HTML 模板自查表（表题连续编号，全表总数 7)、docx 导出新增 checklist 分支（标准+满足数+条目表+note);Table 1 变量概况/主结果表（CI+p 列）/诊断/校准章节此前 T6.3-T6.4 已就位，本任务补齐最后一环（自查+导出）。
  - **测试**:`test_report_checklist.py` 11 例（真实数值进依据/EPV 边界/缺数据降级/契约形状）+ context/template 套件新增自查章节断言（章节顺序、表 5 报告规范自查、表 7 软件版本）；报告相关 9 套件 77 例全绿；ruff/mypy 改动文件全净。
- **T6.12 模型分层套餐**：每任务"标准套餐"3–5 个（基线+强模型+可解释模型），其余折叠为高级选项，取代堆量。✅
  - **落地**:`engines/model_tiers.py`（纯引擎）——标准套餐：分类 logreg/rf/xgboost、回归 lasso/rf_reg/gam/xgboost_reg、生存 coxph/rsf/gbs，角色标注（基线/强模型/可解释）随套餐给出；tier 与任务类型相关（gam 回归=standard/分类=advanced）;`ModelPlugin` 契约新增 `tier`/`role`(docs/14 §5 变更记录 2026-08-27),`GET /models` 按查询任务判定分层且标准套餐在前；前端向导 Step 4 默认仅勾选标准套餐，高级选项折叠展示（Collapse)。**顺带修复存量缺陷**：补建 `engines/adapters.py`(BaseModelAdapter 名义基类，phase2a 遗漏致 gam/gee/poisson/dlnm 四插件从未加载）、补建 `tests/fixtures/poisson_data.py` 合成夹具、`timeseries_cv` 移出与 `preprocessing.py` 同名的目录（模块/包冲突致测试收集失败）——T6.9 模板推荐的 gam/gee 至此真正可用。
  - **测试**:`test_model_tiers.py` 12 例（套餐规模 3–5/key 合法且真实注册/角色齐备/tier 任务相关）+ `test_admin_plugins.py` 新增 4 例（tier/role 字段、标准在前排序、跨任务分层、admin 视图）+ 四插件既有套件（gam 11/gee/poisson/dlnm）随修复转绿；全量 sweep 除 5 例存量失败（test_statistical_tests×3、test_e2e、test_preprocess_recommend,HEAD 上同样失败，与本次无关）外全绿；ruff/mypy 改动文件全净，前端 tsc 净。
- **T6.13 对话式迭代**:LLM 回答"如果把 X 当协变量会怎样" → 生成重跑建议。✅
  - **落地**:`engines/iteration.py` 规则版兜底恒可用（列名长名优先匹配、剔除词识别、未知列名回声提示、结局列自动排除、回答只引用 comparison 真实指标均值）;LLM 增强走 `llm_tasks.generate_iteration_advice`(JSON-only 输出 → 列名/模型白名单校验 + 幻觉数值校验，任一不合格回退规则版，红线8)，新增 `iteration` 分功能开关（默认 off,AI 设置页可配）;POST /analysis-runs/{id}/iterate(docs/14 §5 变更记录 2026-08-27)，响应含 suggestion(add/drop_features/selected_models)+ dataset_id/project_id，审计 analysis.iterate；前端比较页性能表 Tab 内嵌「迭代问答」卡（AI 增强/规则回答标记、建议标签化）,「按建议重跑」跳分析向导经 location.state 预填模型集并把 add/drop 落到 drop_columns 步骤。
  - **测试**:`test_iteration.py` 8 例 + `test_iterate_api.py` 6 例（规则兜底/LLM 失败回退/401/404/400)+ llm_settings/llm_wiring 联动共 57 例全绿；全量回归仅剩 T6.12 已核实的 5 例存量失败；ruff/mypy 改动文件全净，前端 tsc 通过。
- **T6.14 数据缺口建议（"还需补充哪类数据"）**：规则引擎计算缺口，LLM 只做表达润色。📋 已立项（docs-first，2026-09-09），实现待续。
  - **决策依据**（对话落档）：用户询问"是否交给 LLM 识别和分析"——否。判断/计算必须确定性（红线 8：禁止编造数值与医学断言；LLM 红线：facts-only、本地 Ollama 优先）。"建议再收 N 例"这类结论若由 LLM 生成即为无依据编造，正是客户抱怨"不专业"的根源。
  - **落地计划**：`engines/supplement_advisor.py`（纯引擎，无新依赖，power 用技术栈已有 statsmodels）——五类缺口：① EPV 不足：缺口事件 = ⌈10×特征数 − 阳性数⌉，按当前阳性率折算**需补样本量** ⌈缺口事件/阳性率⌉；② 类别不均衡：阳性率 <10% 时给出最低建模所需阳性例数；③ 生存事件不足：事件数 <100 的缺口与随访建议；④ 变量角色缺失：按研究类型规则（队列缺随访时间/事件列、缺年龄/性别等常规基线变量）；⑤ 组间比较把握度：检测到分组列时真实 power 计算。每条输出 `{deficit_type, current, target, gap, suggestion, basis}`，数值全部真实计算、依据可展开。接入 `auto_dataset_insight`（阶段 A 第 4 步）落 `DatasetInsight.payload.supplement_plan`；前端体检卡展示；同时接入报告动态局限性清单数据源。LLM 润色为**后续子项**（复用 T6.7 接线：facts-only + 幻觉校验 + 模板兜底），首版仅规则 + 模板文案。
  - **DoD**：引擎测试先行（docs/19 单元测试类）；五类缺口各有真实数值用例 + 边界（空数据/健康数据不出误报）；insight API 断言 supplement_plan 结构；engines 覆盖率 ≥85%；docs/14 §5 变更记录已登记；全量回归绿；ruff/mypy/前端 tsc 净。
  - **测试计划**：`test_supplement_advisor.py`（EPV 折算公式与边界/不均衡阈值/生存事件阈值/变量角色规则/power 真实值/空表不崩）+ insight API 套件增补结构断言。
- **T6.15 报告可读性与科学诚实整改**。📋 已立项（docs-first，2026-09-09），实现待续。
  - **背景实据**（服务器生成报告 report-434b9064.html 逐章解剖，2026-09-09）：正文 llm-paragraph 元素 0 个——LLM 一次未调用成功（服务器未部署 Ollama，静默回退模板），全部文字为模板/规则句式；§8 临床意义解读仅 206 字；§5 p 值列出现 nan（配对差异零方差，引擎修复已在 main 待服务器更新）；§1 分类任务误渲染"事件数：；中位随访时间：。"空字段；§3 预处理参数以原始 JSON + \uXXXX 转义直出；最严重：n=92、40 变量、EPV=0.7、三模型 AUC=1.0000（教科书级过拟合/疑似数据泄漏），第 11 章结论照常"推荐 catboost（auc=1.0000）"无警示。
  - **决策依据**（对话落档）：润色不能包装误导性结论——科学诚实优先于表达美观，故红旗警示为 P0 而非表达层的附属；模板加厚有天花板（只能做指标级解释，数据特定临床叙事真实依赖 LLM），两层缺一不可：规则保底线、LLM 保上限；7b 本地模型解读质量未经实测不先承诺，不达标则不启用（幻觉校验拦得住数字编造、拦不住平庸废话）。
  - **范围五项（每项独立提交）**：① P0 渲染修复：p 值 nan → "—"渲染守卫（引擎修复之外的双保险）；§1 非生存任务不渲染生存空字段；§3 预处理参数人性化（unicode 解码 + 可读格式化）。✅（2026-09-09：引擎 `_compute_pvalue` nan 守卫 + 模板 `fmt_num` 过滤器双保险；§1 守卫修 Jinja Undefined is not none 陷阱；context `_humanize_params` 键=值 可读化，附录保留原始 steps；模板版本 1.1.1；test_report_render_fixes.py 13 例）② P0 完美指标红旗：EPV<10 且主指标≥0.99 → limitations 动态条目 + 结论章强制醒目警示 + 推荐措辞降级（"结果过于完美，疑似过拟合/数据泄漏，投稿前必须核查"），并点名 Top1 特征提示核查结局代理变量（引用真实特征名，不做因果断言）。③ P1 模板三段式加厚：模型性能/比较推荐/特征重要性/临床意义四章，每指标"含义 / 判读规则 / 本数据数值结论"三段，数字全部来自 payload 真实值（红线 8）；LLM 缺失时报告仍达可读底线。④ Ollama 服务器交接包：部署命令 + 冒烟脚本（连通性/幻觉拦截/降级回退/内存水位）+ 结果回传格式。⑤ 全量回归 + 同一 run 前后两份报告对比。
  - **风险与合理性评估**：改动集中在报告层（engines/reporting/* 与模板），不触碰分析编排/模型计算路径，爆炸半径小；红旗只改措辞与新增警示段落，不改排名数值，历史 run 重出报告行为一致；模板加厚仅增加段落，契约（ReportContext payload 键）只增不改，前端报告页不消费 payload 内部键不受影响；无新依赖。
  - **DoD**：① 项：同一 payload 渲染后无 nan/无"事件数：；"/预处理参数人读可达；② 项：红旗用例（EPV=0.7+AUC=1.0 合成 payload）结论章含警示且引用真实 EPV/指标值，健康 payload 不出警示；③ 项：四章各指标段含三段式结构断言；每项测试先行，engines 覆盖率 ≥85%，全量回归绿，ruff/mypy/前端 tsc 净。
  - **终验（防虚假达成）**：不看"我们觉得变好"，看读者——同一份 run 整改前后两份报告，请一位临床读者盲读，能复述"这份数据能得出什么、不能得出什么"才算过。
  - **测试计划**：`test_report_redflags.py`（红旗触发/不触发/措辞降级/真实数值引用/Top1 特征点名）+ `test_report_render_fixes.py`（nan→"—"/分类任务无生存空字段/预处理参数可读化）+ context/template 套件增补三段式结构断言。
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
