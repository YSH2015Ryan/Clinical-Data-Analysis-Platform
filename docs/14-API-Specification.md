# 14. API 规范（API Specification）

> REST + JSON，FastAPI 自动生成 OpenAPI 3.1（`/openapi.json`，Swagger UI `/docs`）。所有响应错误遵循 RFC7807 风格。Base URL：`/api/v1`。

## 1. 通用约定

- 认证：`Authorization: Bearer <JWT>`（除 /auth/login、/healthz）。
- 分页：`?cursor=&limit=50` → `{"items":[...], "next_cursor": "..."}`。
- 错误响应：
```json
{"code": "DATASET_NOT_FOUND", "message": "数据集不存在或已被删除",
 "details": {"dataset_id": "…"}, "trace_id": "…"}
```

## 2. 错误码表

| HTTP | code | 说明 |
|---|---|---|
| 400 | VALIDATION_ERROR | 请求体/参数校验失败 |
| 400 | UNSUPPORTED_FILE_TYPE | 文件类型不在白名单 |
| 400 | DATASET_HAS_BLOCKERS | 存在阻塞级质量问题，禁止提交分析（前端：禁用提交按钮并跳转质量报告） |
| 400 | DATASET_NOT_READY | 数据集校验中或校验失败，不可用于创建 run（前端：引导等待/重新上传） |
| 400 | PLUGIN_UNAVAILABLE | 所选模型已禁用或与 task_type 不匹配（前端：刷新模型列表） |
| 400 | REPORT_NOT_READY | 报告仍在生成中，不可下载（前端：继续轮询） |
| 400 | INVALID_RUN_STATE | 当前状态不允许该操作（如 COMPLETED 的 run 不可取消） |
| 401 | AUTH_FAILED / TOKEN_EXPIRED | 认证失败 |
| 403 | FORBIDDEN | 无权访问该资源 |
| 404 | PROJECT_NOT_FOUND / DATASET_NOT_FOUND / RUN_NOT_FOUND / REPORT_NOT_FOUND | 资源不存在 |
| 409 | RUN_ALREADY_ACTIVE | 同数据集已有进行中的分析 |
| 413 | FILE_TOO_LARGE | 超过大小上限 |
| 422 | TASK_TYPE_UNDETECTED | 无法识别任务类型，需手动指定（前端：回退手动选择） |
| 500 | INTERNAL_ERROR | 未预期错误（附 trace_id） |
| 503 | WORKER_UNAVAILABLE | 队列不可用 |

> 前端消费约定：每个 4xx code 对应唯一 UI 行为（见表中「前端：」标注）；新增 code 必须在 PR 中声明其 UI 行为。

## 3. OpenAPI 规范（核心路径，YAML 节选）

```yaml
openapi: 3.1.0
info:
  title: CDAP API
  version: 1.0.0
servers: [{url: /api/v1}]
tags: [auth, projects, datasets, analysis, reports, admin]

paths:
  /auth/login:
    post:
      tags: [auth]
      summary: 登录获取 JWT
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/LoginRequest'}
      responses:
        '200':
          description: 成功
          content:
            application/json:
              schema: {$ref: '#/components/schemas/TokenResponse'}
        '401': {$ref: '#/components/responses/Error'}

  /auth/refresh:
    post:
      tags: [auth]
      summary: 刷新 access token
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/RefreshRequest'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/TokenResponse'}
        '401': {$ref: '#/components/responses/Error'}

  /projects:
    get:
      tags: [projects]
      summary: 我的项目列表（分页）
      parameters:
        - {name: cursor, in: query, schema: {type: string}}
        - {name: limit, in: query, schema: {type: integer, default: 50, maximum: 100}}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/ProjectPage'}
    post:
      tags: [projects]
      summary: 创建项目
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/ProjectCreate'}
      responses:
        '201':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Project'}

  /projects/{project_id}:
    delete:
      tags: [projects]
      summary: 删除项目（软删；仅 owner/admin，viewer 403）
      parameters: [{name: project_id, in: path, required: true, schema: {type: string, format: uuid}}]
      responses:
        '204': {description: 已删除}
        '403': {$ref: '#/components/responses/Error'}
        '404': {$ref: '#/components/responses/Error'}

  /projects/{project_id}/datasets:
    get:
      tags: [datasets]
      summary: 项目内数据集列表（分页）
      parameters:
        - {name: project_id, in: path, required: true, schema: {type: string, format: uuid}}
        - {name: cursor, in: query, schema: {type: string}}
        - {name: limit, in: query, schema: {type: integer, default: 50, maximum: 100}}
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  items: {type: array, items: {$ref: '#/components/schemas/DatasetDetail'}}
                  next_cursor: {type: string, nullable: true}
    post:
      tags: [datasets]
      summary: 上传数据集（multipart）
      parameters: [{name: project_id, in: path, required: true, schema: {type: string, format: uuid}}]
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              required: [file]
              properties:
                file: {type: string, format: binary}
                name: {type: string}
      responses:
        '202':
          description: 已接收，异步校验中
          content:
            application/json:
              schema: {$ref: '#/components/schemas/DatasetAccepted'}
        '400': {$ref: '#/components/responses/Error'}
        '413': {$ref: '#/components/responses/Error'}

  /projects/{project_id}/analysis-runs:
    get:
      tags: [analysis]
      summary: 项目内分析运行列表（分页，项目工作台）
      parameters:
        - {name: project_id, in: path, required: true, schema: {type: string, format: uuid}}
        - {name: cursor, in: query, schema: {type: string}}
        - {name: limit, in: query, schema: {type: integer, default: 50, maximum: 100}}
        - {name: status, in: query, schema: {$ref: '#/components/schemas/RunStatus'}}
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  items: {type: array, items: {$ref: '#/components/schemas/AnalysisRun'}}
                  next_cursor: {type: string, nullable: true}

  /datasets/{dataset_id}/versions:
    get:
      tags: [datasets]
      summary: 数据集版本列表（Quick Fix 历史，供创建 run 时选择）
      parameters: [{name: dataset_id, in: path, required: true, schema: {type: string, format: uuid}}]
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items: {$ref: '#/components/schemas/DatasetVersion'}

  /models:
    get:
      tags: [analysis]
      summary: 可用模型列表（按任务类型过滤，所有登录用户可读；含 T6.12 分层 tier/role，标准套餐在前）
      parameters:
        - {name: task_type, in: query, required: true, schema: {type: string, enum: [survival, classification, regression]}}
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items: {$ref: '#/components/schemas/ModelPlugin'}

  /datasets/{dataset_id}:
    get:
      tags: [datasets]
      summary: 数据集详情（含预览与列画像）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/DatasetDetail'}

  /datasets/{dataset_id}/quality-report:
    get:
      tags: [datasets]
      summary: 最新质量报告
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/QualityReport'}

  /datasets/{dataset_id}/quick-fix:
    post:
      tags: [datasets]
      summary: 在线修复（生成新版本）
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/QuickFixRequest'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/DatasetVersion'}

  /datasets/{dataset_id}/research-profile:
    post:
      tags: [datasets]
      summary: 研究画像（规则引擎识别研究设计并推荐模型/期刊；T6.7 起 research_profile 开关打开时附 LLM 研究问题建议）
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/ResearchHints'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/ResearchProfile'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/research-templates:
    get:
      tags: [datasets]
      summary: 科研流程模板库（T6.9）：预后模型/危险因素/剂量反应/纵向四类模板，按数据集真实统计给出适用性、推荐任务/模型/图表与样本量/功效提示（全部数值真实计算，不虚构）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/ResearchTemplatesResponse'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/univariate-screen:
    post:
      tags: [datasets]
      summary: 单因素筛选（T6.10）：逐特征与结局的关联检验（分类=Mann-Whitney/卡方，生存=单因素Cox，回归=相关/方差分析），p<alpha 入选供多因素建模；全部统计量真实计算
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/UnivariateScreenRequest'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/UnivariateScreenResult'}
        '400': {$ref: '#/components/responses/Error'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/subgroup-analysis:
    post:
      tags: [datasets]
      summary: 亚组分析（T6.10）：按亚组变量分层估计暴露效应（OR/HR/β + 95%CI）并给出交互作用 p 值；全部统计量真实计算
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/SubgroupAnalysisRequest'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/SubgroupAnalysisResult'}
        '400': {$ref: '#/components/responses/Error'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/preprocess/validate:
    post:
      tags: [datasets]
      summary: 预处理 DSL 校验（前端配置面板即时校验；非法 DSL 400）
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/PreprocessConfig'}
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  valid: {type: boolean}
                  normalized: {$ref: '#/components/schemas/PreprocessConfig'}
        '400': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/preprocess/recommend:
    post:
      tags: [datasets]
      summary: 推荐默认预处理配置（按列类型/语义生成，docs/06 §2「推荐配置」按钮数据源）
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  config: {$ref: '#/components/schemas/PreprocessConfig'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/preparation/preview:
    post:
      tags: [datasets]
      summary: 数据准备预览（契约变更 2026-08-03，docs/05 §8）：扫描长表+诊断表，返回列识别/词条/统计
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [diagnosis_dataset_id]
              properties:
                diagnosis_dataset_id: {type: string, format: uuid}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/PreparationPreview'}
        '400': {$ref: '#/components/responses/Error'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/preparation/apply:
    post:
      tags: [datasets]
      summary: 提交数据准备（契约变更 2026-08-03）：按决策生成长表→宽表任务，202 异步
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [diagnosis_dataset_id, decisions]
              properties:
                diagnosis_dataset_id: {type: string, format: uuid}
                decisions: {$ref: '#/components/schemas/PreparationDecisions'}
      responses:
        '202':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/PreparationJob'}
        '400': {$ref: '#/components/responses/Error'}

  /preparations/{preparation_id}:
    get:
      tags: [datasets]
      summary: 数据准备任务状态与结果（契约变更 2026-08-03）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/PreparationJob'}
        '404': {$ref: '#/components/responses/Error'}

  /datasets/{dataset_id}/detect-task:
    post:
      tags: [analysis]
      summary: 自动识别分析任务类型
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/TaskDetectionResult'}
        '422': {$ref: '#/components/responses/Error'}

  /analysis-runs:
    post:
      tags: [analysis]
      summary: 创建分析运行
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/AnalysisRunCreate'}
      responses:
        '202':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/AnalysisRun'}
        '400': {$ref: '#/components/responses/Error'}
        '409': {$ref: '#/components/responses/Error'}

  /analysis-runs/{run_id}:
    get:
      tags: [analysis]
      summary: 运行详情（含状态机状态）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/AnalysisRunDetail'}

  /analysis-runs/{run_id}/progress:
    get:
      tags: [analysis]
      summary: 运行进度（轮询）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/RunProgress'}

  /analysis-runs/{run_id}/cancel:
    post:
      tags: [analysis]
      summary: 取消运行
      responses: {'200': {description: 已取消}, '400': {$ref: '#/components/responses/Error'}}

  /analysis-runs/{run_id}/comparison:
    get:
      tags: [analysis]
      summary: 模型比较结果（性能表/排名/图表数据）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/ComparisonResult'}

  /analysis-runs/{run_id}/models/{model_key}/rerun:
    post:
      tags: [analysis]
      summary: 单模型重跑
      responses: {'202': {description: 已入队}}

  /analysis-runs/{run_id}/iterate:
    post:
      tags: [analysis]
      summary: 对话式迭代（T6.13）：提问「如果把 X 当协变量会怎样」→ 回答 + 结构化重跑建议；LLM 关闭/失败时规则引擎兜底
      parameters: [{name: run_id, in: path, required: true, schema: {type: string, format: uuid}}]
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/IterateRequest'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/IterateResponse'}

  /analysis-runs/{run_id}/reports:
    get:
      tags: [reports]
      summary: 该运行的报告历史列表
      parameters: [{name: run_id, in: path, required: true, schema: {type: string, format: uuid}}]
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items: {$ref: '#/components/schemas/Report'}

  /analysis-runs/{run_id}/events:
    get:
      tags: [analysis]
      summary: （可选增强）SSE 进度推送；未实现时前端回退轮询 /progress
      parameters: [{name: run_id, in: path, required: true, schema: {type: string, format: uuid}}]
      responses:
        '200':
          description: text/event-stream，事件载荷同 RunProgress
          content:
            text/event-stream:
              schema: {$ref: '#/components/schemas/RunProgress'}

  /reports:
    post:
      tags: [reports]
      summary: 生成报告
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/ReportCreate'}
      responses:
        '202':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Report'}

  /reports/{report_id}/download:
    get:
      tags: [reports]
      summary: 下载报告（302 → 预签名 URL）
      responses:
        '302': {description: 重定向到 S3 预签名地址}
        '400': {description: REPORT_NOT_READY——报告仍在生成中}
        '404': {$ref: '#/components/responses/Error'}

  /admin/plugins:
    get:
      tags: [admin]
      summary: 模型插件列表（admin）
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items: {$ref: '#/components/schemas/ModelPlugin'}

  /admin/plugins/{key}:
    patch:
      tags: [admin]
      summary: 启用/禁用插件、更新默认参数
      responses: {'200': {description: 已更新}}

  /admin/settings/llm:
    get:
      tags: [admin]
      summary: LLM 配置与 provider 状态（admin；云端 key 只回显掩码）
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/LlmSettingsOut'}
    put:
      tags: [admin]
      summary: 更新 LLM 运行层配置（admin；立即生效不重启；key 只写不读）
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/LlmSettingsUpdate'}
      responses: {'200': {description: 已更新, content: {application/json: {schema: {$ref: '#/components/schemas/LlmSettingsOut'}}}}}

  /admin/settings/llm/test:
    post:
      tags: [admin]
      summary: 真实连通性测试（admin；发最小请求测延迟）
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/LlmTestRequest'}
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/LlmTestResult'}

  /admin/settings/llm/ollama-models:
    get:
      tags: [admin]
      summary: Ollama 已安装模型列表代理（admin；免手敲模型名）
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  available: {type: boolean}
                  models: {type: array, items: {type: string}}

  /healthz:
    get: {tags: [admin], summary: 存活检查, responses: {'200': {description: ok}}}
  /readyz:
    get: {tags: [admin], summary: 依赖就绪检查, responses: {'200': {description: ok}, '503': {description: not ready}}}

components:
  responses:
    Error:
      description: 错误
      content:
        application/json:
          schema: {$ref: '#/components/schemas/ErrorResponse'}

  schemas:
    LoginRequest:
      type: object
      required: [email, password]
      properties: {email: {type: string, format: email}, password: {type: string}}
    RefreshRequest:
      type: object
      required: [refresh_token]
      properties: {refresh_token: {type: string}}
    TokenResponse:
      type: object
      properties:
        access_token: {type: string}
        refresh_token: {type: string}
        token_type: {type: string, enum: [bearer]}

    ProjectCreate:
      type: object
      required: [name]
      properties: {name: {type: string, maxLength: 120}, description: {type: string}}
    Project:
      type: object
      properties:
        id: {type: string, format: uuid}
        name: {type: string}
        description: {type: string}
        created_at: {type: string, format: date-time}
    ProjectPage:
      type: object
      properties:
        items: {type: array, items: {$ref: '#/components/schemas/Project'}}
        next_cursor: {type: string, nullable: true}

    DatasetAccepted:
      type: object
      properties:
        dataset_id: {type: string, format: uuid}
        status: {type: string, enum: [VALIDATING]}
    DatasetVersion:
      type: object
      properties:
        id: {type: string, format: uuid}
        dataset_id: {type: string, format: uuid}
        version_no: {type: integer}
        transform_log: {type: array, items: {type: object}, description: Quick Fix 操作记录}
        created_at: {type: string, format: date-time}
    DatasetDetail:
      type: object
      properties:
        id: {type: string, format: uuid}
        name: {type: string}
        status: {type: string, enum: [UPLOADED, VALIDATING, VALIDATED, FAILED, ARCHIVED]}
        encoding: {type: string, nullable: true}
        preview: {type: object}
        column_profile: {type: array, items: {type: object}}
    QualityReport:
      type: object
      properties:
        status: {type: string, enum: [PASSED, PASSED_WITH_WARNINGS, FAILED]}
        blockers: {type: integer}
        warnings: {type: integer}
        issues:
          type: array
          items:
            type: object
            properties:
              rule_id: {type: string}
              severity: {type: string, enum: [blocker, warning, info]}
              column: {type: string, nullable: true}
              message: {type: string}
              affected_rows: {type: integer}
              suggestion: {type: string}
              row_indices: {type: array, items: {type: integer}, nullable: true, description: 受影响行号(0 基,升序,≤20;前端展示 Excel 行号=索引+2)}
              guidance: {type: string, nullable: true, description: 富文案修复指引(原因+多种修法+一键操作)}
              llm_explanation: {type: string, nullable: true, description: LLM 人话版修复解释(T6.7;validation_explain 开关打开且生成成功时存在,仅 blocker)}
        column_profiles: {type: array, items: {type: object}}
    QuickFixRequest:
      type: object
      required: [actions]
      properties:
        actions:
          type: array
          items:
            type: object
            required: [type]
            properties:
              type: {type: string, enum: [drop_column, drop_duplicates, to_missing, remap_semantic, rename_column, pivot_long_to_wide, winsorize_outliers, impute_missing, drop_rows_with_pattern, normalize_units]}
              column: {type: string}
              params: {type: object}

    ResearchHints:
      type: object
      description: 研究画像用户提示（全部可选）
      properties:
        research_type: {type: string, nullable: true, description: 期望的研究设计(cohort/time_series/case_control/cross_sectional)}
        time_column: {type: string, nullable: true}
        event_column: {type: string, nullable: true}
        group_column: {type: string, nullable: true}
        outcome: {type: string, nullable: true}
    ResearchQuestion:
      type: object
      required: [question, design, models, charts]
      properties:
        question: {type: string}
        design: {type: string}
        models: {type: array, items: {type: string}, description: 必为 recommended_models 子集}
        charts: {type: array, items: {type: string}, description: 平台图表白名单内}
    ResearchProfile:
      type: object
      required: [research_type, recommended_models, recommended_journals, confidence, reasoning]
      properties:
        research_type: {type: string, enum: [cohort, time_series, case_control, cross_sectional]}
        recommended_models: {type: array, items: {type: string}}
        recommended_journals: {type: array, items: {type: string}}
        confidence: {type: number}
        reasoning: {type: string}
        research_questions: {type: array, items: {$ref: '#/components/schemas/ResearchQuestion'}, nullable: true, description: LLM 研究问题建议(T6.7);开关关闭或 LLM 不可用时为 null,规则结果兜底}

    SampleSizeAdvice:
      type: object
      required: [rule, meets, text]
      properties:
        rule: {type: string, description: 经验规则名称(如 EPV≥10)}
        value: {type: number, nullable: true, description: 当前数据实际值(EPV 或 n/p 等),无法计算时为 null}
        threshold: {type: number, description: 规则阈值}
        meets: {type: boolean, description: 当前数据是否满足规则;value 为 null 时按 false}
        text: {type: string, description: 人话版说明(含真实数值)}
    ResearchTemplateSuggestion:
      type: object
      required: [key, name, description, applicable, reasons, task_type, models, charts, sample_size]
      properties:
        key: {type: string, enum: [prognostic_model, risk_factor, dose_response, longitudinal]}
        name: {type: string}
        description: {type: string}
        applicable: {type: boolean, description: 数据集是否满足该模板的最小数据条件}
        reasons: {type: array, items: {type: string}, description: 适用/不适用的判定理由(含真实列名与数值)}
        task_type: {type: string, enum: [survival, classification, regression]}
        models: {type: array, items: {type: string}, description: 推荐模型 key(模型注册表内)}
        charts: {type: array, items: {type: string}, description: 推荐图表 kind(docs/14 ChartAsset.kind 枚举内)}
        sample_size: {type: array, items: {$ref: '#/components/schemas/SampleSizeAdvice'}}
    ResearchTemplatesResponse:
      type: object
      required: [templates]
      properties:
        templates: {type: array, items: {$ref: '#/components/schemas/ResearchTemplateSuggestion'}}

    UnivariateScreenRequest:
      type: object
      required: [task_type]
      properties:
        task_type: {type: string, enum: [survival, classification, regression]}
        label_col: {type: string, nullable: true, description: 分类/回归结局列}
        time_col: {type: string, nullable: true, description: 生存随访时间列}
        event_col: {type: string, nullable: true, description: 生存事件列}
        features: {type: array, items: {type: string}, nullable: true, description: 待筛特征；为空时自动取除结局外的全部列(上限 50)}
        alpha: {type: number, default: 0.05, description: 入选阈值 p<alpha}
    UnivariateScreenRow:
      type: object
      required: [feature, test, p_value, selected]
      properties:
        feature: {type: string}
        test: {type: string, description: 检验方法名}
        statistic: {type: number, nullable: true, description: 检验统计量(部分方法无)}
        effect: {type: number, nullable: true, description: 效应量(HR/r/中位数差等,视方法而定)}
        p_value: {type: number}
        n_used: {type: integer, description: 实际入检验的非缺失样本数}
        selected: {type: boolean, description: p<alpha}
    UnivariateScreenResult:
      type: object
      required: [task_type, alpha, rows, selected_features]
      properties:
        task_type: {type: string}
        alpha: {type: number}
        rows: {type: array, items: {$ref: '#/components/schemas/UnivariateScreenRow'}, description: 按 p 值升序}
        selected_features: {type: array, items: {type: string}}
    SubgroupAnalysisRequest:
      type: object
      required: [task_type, exposure, subgroup_vars]
      properties:
        task_type: {type: string, enum: [survival, classification, regression]}
        exposure: {type: string, description: 暴露/处理变量(二分类或连续)}
        subgroup_vars: {type: array, items: {type: string}, minItems: 1, description: 亚组变量(分类,2-6 水平)}
        label_col: {type: string, nullable: true}
        time_col: {type: string, nullable: true}
        event_col: {type: string, nullable: true}
    SubgroupLevelEffect:
      type: object
      required: [level, n]
      properties:
        level: {type: string}
        n: {type: integer}
        effect: {type: number, nullable: true, description: 该亚组内暴露效应(OR/HR/β);拟合失败为 null}
        ci_lower: {type: number, nullable: true}
        ci_upper: {type: number, nullable: true}
        note: {type: string, nullable: true, description: 拟合失败原因等}
    SubgroupResult:
      type: object
      required: [variable, levels]
      properties:
        variable: {type: string}
        levels: {type: array, items: {$ref: '#/components/schemas/SubgroupLevelEffect'}}
        interaction_p: {type: number, nullable: true, description: 暴露×亚组交互作用 p 值;无法拟合为 null}
    SubgroupAnalysisResult:
      type: object
      required: [task_type, exposure, subgroups]
      properties:
        task_type: {type: string}
        exposure: {type: string}
        subgroups: {type: array, items: {$ref: '#/components/schemas/SubgroupResult'}}

    TaskDetectionResult:
      type: object
      properties:
        recommended_task: {type: string, enum: [survival, classification, regression], nullable: true}
        confidence: {type: number}
        reason: {type: string}
        candidates: {type: object}
    # 数据准备（契约变更 2026-08-03，docs/05 §8）
    PreparationDecisions:
      type: object
      required: [outcome_terms]
      properties:
        outcome_terms:
          type: array
          minItems: 1
          items: {type: string}
          description: 结局阳性诊断词条（任一命中=1；子串匹配）
        outcome_scope: {type: string, enum: [any, index], default: any}
        index_diagnosis: {type: string, enum: [first, last], default: first}
        window_days: {type: integer, default: 30, minimum: 0, description: 0=不限}
        value_strategy: {type: string, enum: [latest, mean], default: latest}
        value_column: {type: string, default: 归一化值}
        exclude_susceptibility: {type: boolean, default: true}
        clip_quantile: {type: number, default: 0.99, description: 按项目 winsorize；0=不截断}
        top_n_items: {type: integer, default: 200, minimum: 1}
    PreparationPreview:
      type: object
      properties:
        lab_columns: {type: object, description: 识别出的关键列（id/item/value/date/unit/specimen/susceptibility）}
        diag_columns: {type: object}
        lab_rows: {type: integer}
        diag_rows: {type: integer}
        patients_intersection: {type: integer}
        diagnosis_terms:
          type: array
          items:
            type: object
            properties:
              term: {type: string}
              count: {type: integer}
        susceptibility_rows: {type: integer}
        suggested: {$ref: '#/components/schemas/PreparationDecisions'}
    PreparationJob:
      type: object
      properties:
        id: {type: string, format: uuid}
        status: {type: string, enum: [PENDING, RUNNING, COMPLETED, FAILED]}
        result_dataset_id: {type: string, format: uuid, nullable: true}
        summary: {type: object}
        error: {type: string, nullable: true}
        created_at: {type: string, format: date-time}
        finished_at: {type: string, format: date-time, nullable: true}
    AnalysisRunCreate:
      type: object
      required: [dataset_version_id, task_type, preprocess_config, selected_models]
      properties:
        dataset_version_id: {type: string, format: uuid}
        task_type: {type: string, enum: [survival, classification, regression]}
        preprocess_config: {$ref: '#/components/schemas/PreprocessConfig'}
        selected_models:
          type: array
          minItems: 1
          items: {type: string, description: 模型 key，必须属于 /models?task_type= 返回的可用集合，否则 400 PLUGIN_UNAVAILABLE}
        model_params: {type: object, description: 按模型 key 覆盖默认参数，须经插件 JSON Schema 校验}
    # 检查项1 落地：预处理 DSL 内联为强类型 schema（与 06 章 DSL 一一对应）
    PreprocessConfig:
      type: object
      required: [target, steps, validation]
      properties:
        target:
          type: object
          description: 结局定义；survival 用 time_col+event_col，分类/回归用 label_col
          properties:
            time_col: {type: string}
            event_col: {type: string}
            label_col: {type: string}
        steps:
          type: array
          minItems: 1
          items: {$ref: '#/components/schemas/PreprocessStep'}
        validation:
          type: object
          required: [strategy, n_splits, seed]
          properties:
            strategy: {type: string, enum: [stratified_kfold, kfold]}
            n_splits: {type: integer, default: 5, minimum: 2, maximum: 10}
            test_size: {type: number, default: 0.2}
            seed: {type: integer, default: 42}
    PreprocessStep:
      type: object
      required: [type, params]
      properties:
        type:
          type: string
          enum: [reshape, drop_columns, missing, outlier, encode, scale, feature_select, derive]
        params:
          type: object
          description: 各 type 的参数子 schema 在服务端 Pydantic 中定义（06 章 §2），超出公共结构的非法参数返回 400 VALIDATION_ERROR
    RunStatus:
      type: string
      enum: [PENDING, PREPROCESSING, MODELING, COMPARING, COMPLETED, FAILED, CANCELED]
      description: 与 08 章状态机一一对应，不得增删
    ModelTaskStatus:
      type: string
      enum: [PENDING, RUNNING, SUCCESS, FAILED, SKIPPED]
      description: 与 13 章 model_results.status CHECK 约束一致
    AnalysisRun:
      type: object
      properties:
        id: {type: string, format: uuid}
        status: {$ref: '#/components/schemas/RunStatus'}
        task_type: {type: string}
        created_at: {type: string, format: date-time}
    AnalysisRunDetail:
      allOf:
        - {$ref: '#/components/schemas/AnalysisRun'}
        - type: object
          properties:
            task_detection: {type: object}
            error: {type: string, nullable: true}
    RunProgress:
      type: object
      required: [status, percent, models]
      properties:
        status: {$ref: '#/components/schemas/RunStatus'}
        percent: {type: integer, minimum: 0, maximum: 100, description: preprocess 20% + 每模型 70%/N + comparison 10%（08 章 §3）}
        current_step: {type: string, nullable: true}
        models:
          type: object
          additionalProperties: {$ref: '#/components/schemas/ModelTaskStatus'}
        errors:
          type: object
          additionalProperties: {type: string}
          description: 失败模型的错误信息（model_key → error），仅 FAILED 模型出现；前端失败原因 tooltip 数据源
    ComparisonResult:
      type: object
      required: [table, ranking, recommendation, charts]
      properties:
        table:
          type: array
          items: {$ref: '#/components/schemas/ModelMetricsRow'}
        ranking:
          type: array
          items: {type: string}
          description: 按推荐顺序排列的 model_key
        recommendation: {type: object, description: top3+理由+排名公式披露，结构见 04 章 §3}
        charts:
          type: array
          items: {$ref: '#/components/schemas/ChartAsset'}
    ModelMetricsRow:
      type: object
      required: [model_key, status]
      properties:
        model_key: {type: string}
        status: {$ref: '#/components/schemas/ModelTaskStatus'}
        metrics:
          type: object
          description: '指标名 → {mean, std, folds[]}，结构见 04 章 §3；FAILED 行为 null'
          nullable: true
        error: {type: string, nullable: true}
        duration_ms: {type: integer, nullable: true}
    ChartAsset:
      type: object
      required: [kind, title]
      properties:
        kind:
          type: string
          enum: [roc, calibration, dca, confusion_matrix, km, cindex_forest, hr_forest, shap_summary, feature_importance]
        title: {type: string}
        data: {type: object, description: 前端 ECharts 渲染数据}
        image_uri: {type: string, nullable: true, description: 报告用 PNG 的存储 uri}
    ReportCreate:
      type: object
      required: [run_id, format]
      properties:
        run_id: {type: string, format: uuid}
        format: {type: string, enum: [pdf, html, markdown, docx]}
        template_key: {type: string, default: clinical_report_zh}
    Report:
      type: object
      properties:
        id: {type: string, format: uuid}
        run_id: {type: string, format: uuid}
        status: {type: string, enum: [PENDING, READY, FAILED]}
        format: {type: string, enum: [pdf, html, markdown, docx]}
        template_key: {type: string}
        created_at: {type: string, format: date-time}
    ModelPlugin:
      type: object
      properties:
        key: {type: string}
        name: {type: string}
        version: {type: string}
        task_types: {type: array, items: {type: string}}
        capability: {type: object}
        enabled: {type: boolean}
        tier: {type: string, enum: [standard, advanced], description: T6.12 模型分层——standard=标准套餐（向导默认勾选），advanced=高级选项（折叠展示）}
        role: {type: string, nullable: true, description: 标准套餐内角色标注（如 基线·可解释 / 强模型），高级选项为 null}
    LlmFeatureSwitch:
      type: string
      enum: [off, local, local_first, cloud]
      description: 分功能开关：关闭 / 仅本地 / 本地优先(降级云端) / 仅云端
    LlmSettingsOut:
      type: object
      properties:
        status:
          type: object
          properties:
            local: {type: object, description: "{available, provider, model}"}
            cloud: {type: object, description: "{available, provider, model}"}
            default_choice: {type: string, enum: [auto, local, cloud]}
        config:
          type: object
          properties:
            model_choice: {type: string, enum: [auto, local, cloud]}
            temperature: {type: number}
            ollama_model: {type: string}
            cloud_enabled: {type: boolean, description: 部署层是否允许云端（env 锁定）}
            cloud_has_key: {type: boolean}
            cloud_key_preview: {type: string, description: "掩码回显，如 sk-****abcd；无 key 为空串"}
            feature_switches:
              type: object
              properties:
                research_profile: {$ref: '#/components/schemas/LlmFeatureSwitch'}
                report_interpretation: {$ref: '#/components/schemas/LlmFeatureSwitch'}
                validation_explain: {$ref: '#/components/schemas/LlmFeatureSwitch'}
                iteration: {$ref: '#/components/schemas/LlmFeatureSwitch'}
    LlmSettingsUpdate:
      type: object
      properties:
        model_choice: {type: string, enum: [auto, local, cloud]}
        temperature: {type: number, minimum: 0, maximum: 1}
        ollama_model: {type: string}
        openai_api_key: {type: string, description: 只写不读；传空串清除；不传保持原值}
        feature_switches:
          type: object
          properties:
            research_profile: {$ref: '#/components/schemas/LlmFeatureSwitch'}
            report_interpretation: {$ref: '#/components/schemas/LlmFeatureSwitch'}
            validation_explain: {$ref: '#/components/schemas/LlmFeatureSwitch'}
            iteration: {$ref: '#/components/schemas/LlmFeatureSwitch'}
    LlmTestRequest:
      type: object
      required: [provider]
      properties:
        provider: {type: string, enum: [local, cloud]}
    LlmTestResult:
      type: object
      properties:
        ok: {type: boolean}
        provider: {type: string}
        latency_ms: {type: integer}
        detail: {type: string, description: 失败原因（不含密钥等敏感信息）}
    IterateRequest:
      type: object
      required: [question]
      properties:
        question: {type: string, minLength: 1, maxLength: 500}
    RerunSuggestion:
      type: object
      properties:
        summary: {type: string}
        add_features: {type: array, items: {type: string}, description: 建议纳入的协变量（数据集真实列，白名单校验）}
        drop_features: {type: array, items: {type: string}}
        selected_models: {type: array, items: {type: string}, nullable: true, description: 建议模型集（任务可用模型白名单）；null=无需调整}
    IterateResponse:
      type: object
      properties:
        answer: {type: string, description: 只引用该运行真实指标（红线8）}
        suggestion: {$ref: '#/components/schemas/RerunSuggestion', nullable: true}
        llm_enhanced: {type: boolean, description: true=LLM 增强；false=规则回退}
        dataset_id: {type: string, format: uuid, description: 「按建议重跑」跳转向导的数据集预选}
        project_id: {type: string, format: uuid, description: 向导路由所需项目 id}
    ErrorResponse:
      type: object
      properties:
        code: {type: string}
        message: {type: string}
        details: {type: object}
        trace_id: {type: string}
```

## 4. 版本与兼容

- URL 前缀 `/api/v1`；破坏性变更升 v2，v1 保留至少一个版本周期。
- 新增可选字段不算破坏性变更；前端客户端由 OpenAPI 自动生成，CI 校验 schema 与实现一致（schemathesis，见 19 章）。

## 5. 契约冻结声明（v1.0-frozen，2026-07-29）

本章经评审修订后**冻结为基线 `v1.0-frozen`**，作为 M1 起前后端并行开发的唯一契约依据。

**评审结论**（2026-07-29 完成）：

| 检查项 | 结论 | 处置 |
|---|---|---|
| 1. `preprocess_config` 开放 JSON | ❌ 不通过（原状） | 已内联为 `PreprocessConfig`/`PreprocessStep` 强类型 schema |
| 2. 错误码覆盖前端场景 | ❌ 缺 3 个 | 新增 `DATASET_NOT_READY`、`PLUGIN_UNAVAILABLE`、`REPORT_NOT_READY`，并标注每个 code 的 UI 行为 |
| 3. 状态枚举与状态机一致 | ⚠️ 基本一致但无约束 | 抽出 `RunStatus`/`ModelTaskStatus` 单一引用源，禁止增删 |

**评审中额外修复的 8 处缺陷**：补 `/auth/refresh`、`GET /projects/{id}/datasets`、`GET /projects/{id}/analysis-runs`、`GET /datasets/{id}/versions`、`GET /models`（非 admin 读模型列表）、`GET /analysis-runs/{id}/reports`（报告历史）、`GET /analysis-runs/{id}/events`（SSE 可选增强）、补 `DatasetVersion` schema 并收紧 `ComparisonResult`（`ModelMetricsRow`/`ChartAsset`）。

**冻结后变更流程**（违反视为缺陷）：

1. 修改本章 → 2. PR 中标注「契约变更」并说明受影响消费方（前端/报告引擎/测试）→ 3. 重新生成前端类型 → 4. 相关模块同 PR 适配。
- 非破坏性变更（新增端点/可选字段/新错误码）：可直接走上述流程。
- 破坏性变更（删改字段、收窄枚举、改语义）：冻结期内原则上拒绝；确需变更须升 `/api/v2` 并保留 v1。

**冻结后变更记录**：

| 日期 | 变更 | 类型 | 原因 |
|---|---|---|---|
| 2026-07-29 | `PreprocessStep.type` 枚举新增 `reshape` | 非破坏（扩展枚举） | 真实数据为长表（EAV）格式，需长转宽步骤，见 06 章 §3.1、01 章 FR-3.9 |
| 2026-07-29 | 新增 `DELETE /projects/{project_id}`（204 软删） | 非破坏（新增端点） | T1.3 DoD 要求项目可删（软删）；受影响消费方：前端项目列表页 |
| 2026-07-29 | `RunProgress` 新增可选 `errors`（model_key → 错误信息） | 非破坏（新增可选字段） | T5.10 运行监控页「失败原因 tooltip」需逐模型错误文本；受影响消费方：前端 RunProgressBoard |
| 2026-07-30 | 新增 `POST /datasets/{dataset_id}/preprocess/validate` | 非破坏（新增端点） | T3.1 DoD「非法 DSL 400」前置落地 + T3.6 前端配置面板即时校验；受影响消费方：前端预处理面板 |
| 2026-07-30 | 新增 `POST /datasets/{dataset_id}/preprocess/recommend` | 非破坏（新增端点） | T3.5 推荐配置生成器落地 + T3.6 前端「推荐配置」一键填充；受影响消费方：前端预处理面板 |
| 2026-08-03 | 新增 `POST /datasets/{id}/preparation/preview`、`POST /datasets/{id}/preparation/apply`、`GET /preparations/{id}` + PreparationDecisions/Preview/Job schema | 非破坏（新增端点） | P0-1 数据准备向导（05 §8）：真实 EHR 长表组装为宽表；受影响消费方：前端数据准备向导页、worker（新任务）、DB（新表 preparation_jobs） |
| 2026-08-28 | `QualityReport.issues[]` 新增可选 `row_indices`（受影响行号，0 基 ≤20）与 `guidance`（富文案修复指引） | 非破坏（新增可选字段） | T6.1 校验报错可操作化：客户反馈阻塞报错看不懂、不会修；受影响消费方：前端 DatasetDetailPage 问题清单 |
| 2026-08-28 | `QuickFixAction.type` 枚举新增 6 值：`rename_column`/`pivot_long_to_wide`/`winsorize_outliers`/`impute_missing`/`drop_rows_with_pattern`/`normalize_units` | 非破坏（扩展枚举） | T6.8 quick-fix 全覆盖：高发规则（RV201/501/601/802/804）一键修复；受影响消费方：前端 DatasetDetailPage 修复按钮、worker quick-fix 任务 |
| 2026-08-28 | 新增 `GET/PUT /admin/settings/llm`、`POST /admin/settings/llm/test`、`GET /admin/settings/llm/ollama-models` + LlmSettingsOut/Update/LlmTestRequest/LlmTestResult/LlmFeatureSwitch schema | 非破坏（新增端点） | T6.6 LLM 设置界面：运行层配置（模型策略/分功能开关/云端 key/温度）管理员可视化调整免改代码；云端 key 只写不读（掩码回显）；受影响消费方：前端 AI 设置页（新建）、DB（新表 admin_settings）、worker/启动流程（init_llm_service 从 DB 注入） |
| 2026-08-27 | 补录 `POST /datasets/{dataset_id}/research-profile` + ResearchHints/ResearchProfile/ResearchQuestion schema；`ResearchProfile` 新增可选 `research_questions`（LLM 研究问题建议） | 非破坏（补录端点 + 新增可选字段） | T6.7 LLM 接线（研究画像增强）：该端点此前未录入契约，本次补录；research_profile 分功能开关打开时返回 LLM 生成的 2-3 个研究问题（模型/图表均来自引擎白名单），关闭或 LLM 不可用时为 null 回退纯规则结果；受影响消费方：前端研究画像展示 |
| 2026-08-27 | `QualityReport.issues[]` 新增可选 `llm_explanation`（LLM 人话版修复解释，仅 blocker） | 非破坏（新增可选字段） | T6.7 LLM 接线（校验报错解释）：validation_explain 分功能开关打开时，校验 worker 为阻塞级问题生成通俗解释（≤5 条），失败回退缺省；受影响消费方：前端 DatasetDetailPage 问题清单 |
| 2026-08-27 | 新增 `GET /datasets/{dataset_id}/research-templates` + ResearchTemplatesResponse/ResearchTemplateSuggestion/SampleSizeAdvice schema | 非破坏（新增端点） | T6.9 科研流程模板库：预后模型/危险因素/剂量反应/纵向四类模板，按数据集真实统计（行数/事件数/特征数）给出适用性判定、推荐任务/模型/图表与样本量经验规则核对（EPV≥10、n/p≥20 等，全部真实计算不虚构）；受影响消费方：前端分析向导模板选择卡片 |
| 2026-08-27 | 新增 `POST /datasets/{dataset_id}/univariate-screen`、`POST /datasets/{dataset_id}/subgroup-analysis` + 对应 Request/Result schema | 非破坏（新增端点） | T6.10 单因素→多因素筛选流程 + 亚组分析：单因素筛选（Mann-Whitney/卡方/单因素Cox/相关/方差分析，p<alpha 入选供多因素建模）与亚组效应估计（OR/HR/β + 95%CI + 交互 p），全部统计量真实计算（红线8）；受影响消费方：前端数据集详情页科研助手卡片 |
| 2026-08-27 | `ModelPlugin` 新增 `tier`（standard/advanced）与 `role`（可空）字段；`GET /models` 响应按标准套餐在前排序 | 非破坏（新增字段） | T6.12 模型分层套餐：每任务标准套餐 3–5 个（基线+强模型+可解释模型），其余折叠为高级选项；分层定义在引擎 `model_tiers.py`（与任务类型相关，非 DB 字段）；受影响消费方：前端分析向导 Step 4 模型选择（默认仅勾选标准套餐，高级选项折叠） |
| 2026-08-27 | 新增 `POST /analysis-runs/{run_id}/iterate` + IterateRequest/IterateResponse/RerunSuggestion schema；LlmSettingsOut/Update 的 feature_switches 新增 `iteration` 开关 | 非破坏（新增端点 + 新增开关键） | T6.13 对话式迭代：针对已完成运行提问（如「把 X 当协变量会怎样」），规则引擎恒可用（列/模型白名单 + 真实指标引用），iteration 开关打开时 LLM 增强回答（幻觉数值拦截，不合格回退规则版）；响应含 dataset_id 供前端「按建议重跑」跳转向导；受影响消费方：前端结果比较页迭代问答卡、分析向导预填 |
