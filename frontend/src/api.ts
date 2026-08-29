/** API 客户端：契约同源 docs/14（/api/v1，Bearer JWT，RFC7807 错误）。 */

const BASE = "/api/v1";
let accessToken: string | null = null;
let restorePromise: Promise<boolean> | null = null;

export interface ApiError {
  code: string;
  message: string;
  details: Record<string, unknown>;
  trace_id: string;
}

export function getToken(): string | null {
  return accessToken;
}

export function setTokens(access: string, refresh: string): void {
  void refresh;
  accessToken = access;
}

export function clearTokens(): void {
  accessToken = null;
}

async function refreshSession(): Promise<boolean> {
  if (restorePromise) return restorePromise;
  restorePromise = fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  })
    .then(async (resp) => {
      if (!resp.ok) return false;
      const tokens = (await resp.json()) as TokenResponse;
      accessToken = tokens.access_token;
      return true;
    })
    .catch(() => false)
    .finally(() => {
      restorePromise = null;
    });
  return restorePromise;
}

export async function restoreSession(): Promise<boolean> {
  if (accessToken) return true;
  return refreshSession();
}

async function parseError(resp: Response): Promise<ApiError> {
  try {
    return (await resp.json()) as ApiError;
  } catch {
    return { code: "INTERNAL_ERROR", message: `HTTP ${resp.status}`, details: {}, trace_id: "" };
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const request = () => {
    const headers = new Headers(init.headers);
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(`${BASE}${path}`, { ...init, headers, credentials: "include" });
  };
  let resp = await request();
  if (resp.status === 401 && !path.startsWith("/auth/")) {
    if (await restoreSession()) resp = await request();
  }
  if (!resp.ok) {
    const err = await parseError(resp);
    if (resp.status === 401) {
      clearTokens();
      window.location.href = "/login";
    }
    throw err;
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

// ---- 契约类型（docs/14 §3；M2 起由 OpenAPI 自动生成） ----

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface ProjectPage {
  items: Project[];
  next_cursor: string | null;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function listProjects(): Promise<ProjectPage> {
  return apiFetch<ProjectPage>("/projects");
}

export async function createProject(name: string, description: string): Promise<Project> {
  return apiFetch<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export async function deleteProject(id: string): Promise<void> {
  return apiFetch<void>(`/projects/${id}`, { method: "DELETE" });
}

// ---- 数据集（docs/14 §3 DatasetDetail/QualityReport） ----

export interface DatasetDetail {
  id: string;
  name: string;
  status: "UPLOADED" | "VALIDATING" | "VALIDATED" | "FAILED" | "ARCHIVED";
  encoding: string | null;
  preview: { columns: string[]; rows: unknown[][]; total_rows: number } | null;
  column_profile: ColumnProfile[] | null;
}

export interface DatasetPage {
  items: DatasetDetail[];
  next_cursor: string | null;
}

export interface ColumnProfile {
  name: string;
  inferred_type: string;
  semantic: string | null;
  semantic_confidence?: number;
  missing_rate: number;
  unique: number;
  outliers?: number;
  min?: number;
  max?: number;
}

export interface Issue {
  rule_id: string;
  severity: "blocker" | "warning" | "info";
  column: string | null;
  message: string;
  detail?: string | null;
  suggestion: string;
  affected_rows: number | null;
  /** T6.1:受影响行号(0 基,升序,≤20;Excel 行号 = 值 + 2) */
  row_indices?: number[] | null;
  /** T6.1:富文案修复指引(原因+多种修法+一键操作),多行纯文本 */
  guidance?: string | null;
}

export interface QualityReport {
  status: "PASSED" | "PASSED_WITH_WARNINGS" | "FAILED";
  blockers: number;
  warnings: number;
  issues: Issue[];
  column_profiles: ColumnProfile[];
}

export async function listDatasets(projectId: string): Promise<DatasetPage> {
  return apiFetch<DatasetPage>(`/projects/${projectId}/datasets`);
}

export const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;

export interface UploadDatasetOptions {
  signal?: AbortSignal;
  onProgress?: (percent: number) => void;
}

function uploadError(xhr: XMLHttpRequest): ApiError {
  try {
    return JSON.parse(xhr.responseText) as ApiError;
  } catch {
    return {
      code: "INTERNAL_ERROR",
      message: xhr.status ? `HTTP ${xhr.status}` : "网络连接中断",
      details: {},
      trace_id: "",
    };
  }
}

export async function uploadDataset(
  projectId: string,
  file: File,
  options: UploadDatasetOptions = {},
): Promise<{ dataset_id: string }> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw {
      code: "FILE_TOO_LARGE",
      message: "文件超过 200 MB 上限，请压缩或拆分后重试",
      details: { max_mb: 200 },
      trace_id: "",
    } satisfies ApiError;
  }

  // Start every upload with a fresh access token. Uploads are intentionally
  // not retried after 401 because replaying a large FormData body starts over.
  if (!(await refreshSession())) {
    clearTokens();
    window.location.href = "/login";
    throw {
      code: "AUTH_FAILED",
      message: "登录已过期，请重新登录",
      details: {},
      trace_id: "",
    } satisfies ApiError;
  }

  const form = new FormData();
  form.append("file", file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    xhr.open("POST", `${BASE}/projects/${projectId}/datasets`);
    xhr.withCredentials = true;
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        options.onProgress?.(Math.min(99, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      options.signal?.removeEventListener("abort", abort);
      if (xhr.status >= 200 && xhr.status < 300) {
        options.onProgress?.(100);
        try {
          resolve(JSON.parse(xhr.responseText) as { dataset_id: string });
        } catch {
          reject(uploadError(xhr));
        }
        return;
      }
      if (xhr.status === 401) clearTokens();
      reject(uploadError(xhr));
    };
    xhr.onerror = () => {
      options.signal?.removeEventListener("abort", abort);
      reject(uploadError(xhr));
    };
    xhr.onabort = () => {
      options.signal?.removeEventListener("abort", abort);
      reject(new DOMException("Upload cancelled", "AbortError"));
    };
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) {
      xhr.abort();
      return;
    }
    xhr.send(form);
  });
}

export async function getDataset(id: string): Promise<DatasetDetail> {
  return apiFetch<DatasetDetail>(`/datasets/${id}`);
}

export async function getQualityReport(id: string): Promise<QualityReport> {
  return apiFetch<QualityReport>(`/datasets/${id}/quality-report`);
}

// ---- Quick Fix（docs/14 §3 POST /datasets/{id}/quick-fix） ----

export interface QuickFixAction {
  type:
    | "drop_column"
    | "drop_duplicates"
    | "to_missing"
    | "remap_semantic"
    // T6.8 扩展
    | "rename_column"
    | "pivot_long_to_wide"
    | "winsorize_outliers"
    | "impute_missing"
    | "drop_rows_with_pattern"
    | "normalize_units";
  column?: string;
  params?: Record<string, unknown>;
}

export interface DatasetVersion {
  id: string;
  dataset_id: string;
  version_no: number;
  transform_log: { action: string; column: string | null; affected_rows: number }[];
  created_at: string;
}

export async function quickFix(datasetId: string, actions: QuickFixAction[]): Promise<DatasetVersion> {
  return apiFetch<DatasetVersion>(`/datasets/${datasetId}/quick-fix`, {
    method: "POST",
    body: JSON.stringify({ actions }),
  });
}

export async function listDatasetVersions(datasetId: string): Promise<DatasetVersion[]> {
  return apiFetch<DatasetVersion[]>(`/datasets/${datasetId}/versions`);
}

export const SEMANTIC_OPTIONS = ["Age", "Gender", "Diagnosis", "FollowUp", "Event", "Label"];

// ---- 数据准备（docs/14 §3 preparation，契约变更 2026-08-03；docs/05 §8） ----

export interface PreparationDecisions {
  outcome_terms: string[];
  outcome_scope: "any" | "index";
  index_diagnosis: "first" | "last";
  window_days: number;
  value_strategy: "latest" | "mean";
  value_column: string;
  exclude_susceptibility: boolean;
  clip_quantile: number;
  top_n_items: number;
}

export interface PreparationPreview {
  lab_columns: Record<string, string | null>;
  diag_columns: Record<string, string | null>;
  lab_rows: number;
  diag_rows: number;
  patients_intersection: number;
  diagnosis_terms: { term: string; count: number }[];
  susceptibility_rows: number;
  suggested: Partial<PreparationDecisions>;
}

export interface PreparationJob {
  id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
  result_dataset_id: string | null;
  summary: Record<string, number> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export async function preparationPreview(
  labDatasetId: string,
  diagnosisDatasetId: string,
): Promise<PreparationPreview> {
  return apiFetch<PreparationPreview>(`/datasets/${labDatasetId}/preparation/preview`, {
    method: "POST",
    body: JSON.stringify({ diagnosis_dataset_id: diagnosisDatasetId }),
  });
}

export async function preparationApply(
  labDatasetId: string,
  diagnosisDatasetId: string,
  decisions: PreparationDecisions,
): Promise<PreparationJob> {
  return apiFetch<PreparationJob>(`/datasets/${labDatasetId}/preparation/apply`, {
    method: "POST",
    body: JSON.stringify({ diagnosis_dataset_id: diagnosisDatasetId, decisions }),
  });
}

export async function getPreparationJob(id: string): Promise<PreparationJob> {
  return apiFetch<PreparationJob>(`/preparations/${id}`);
}

// ---- 预处理 DSL（docs/14 §3 PreprocessConfig；docs/06 §2） ----

export type StepType =
  | "reshape"
  | "drop_columns"
  | "missing"
  | "outlier"
  | "encode"
  | "scale"
  | "feature_select"
  | "derive";

export interface PreprocessStep {
  type: StepType;
  params: Record<string, unknown>;
}

export interface PreprocessConfig {
  target: { time_col?: string | null; event_col?: string | null; label_col?: string | null };
  steps: PreprocessStep[];
  validation: {
    strategy: "stratified_kfold" | "kfold";
    n_splits: number;
    test_size?: number;
    seed: number;
  };
}

export interface ValidateResult {
  valid: boolean;
  normalized: PreprocessConfig;
}

export async function validatePreprocess(
  datasetId: string,
  config: PreprocessConfig,
): Promise<ValidateResult> {
  return apiFetch<ValidateResult>(`/datasets/${datasetId}/preprocess/validate`, {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function recommendPreprocess(datasetId: string): Promise<PreprocessConfig> {
  const resp = await apiFetch<{ config: PreprocessConfig }>(
    `/datasets/${datasetId}/preprocess/recommend`,
    { method: "POST" },
  );
  return resp.config;
}

export const DEFAULT_STEP_PARAMS: Record<StepType, Record<string, unknown>> = {
  reshape: { mode: "long_to_wide", index: "", columns: "", values: "", agg: "first" },
  drop_columns: { columns: [] },
  missing: { default: "median", per_column: {}, drop_threshold: 0.5 },
  outlier: { method: "iqr", action: "clip", columns: "continuous", zscore_threshold: 3.0 },
  encode: { method: "auto", onehot_max_cardinality: 10, ordinal_columns: {} },
  scale: { method: "standard", columns: "continuous" },
  feature_select: { method: "variance_threshold", threshold: 0.0 },
  derive: { expressions: [{ name: "", expr: "" }] },
};

// ---- 任务识别（docs/14 §3 TaskDetectionResult；docs/08 §1.3） ----

export type TaskType = "survival" | "classification" | "regression";

export interface TaskCandidate {
  column: string;
  confidence: number;
}

export interface TaskDetectionResult {
  recommended_task: TaskType | null;
  confidence: number;
  reason: string;
  candidates: {
    time_col?: TaskCandidate[];
    event_col?: TaskCandidate[];
    label_col?: TaskCandidate[];
  };
  user_override: string | null;
}

export async function detectTask(datasetId: string): Promise<TaskDetectionResult> {
  return apiFetch<TaskDetectionResult>(`/datasets/${datasetId}/detect-task`, {
    method: "POST",
  });
}

// ---- 科研流程模板库（T6.9；docs/14 §3 /datasets/{id}/research-templates） ----

export interface SampleSizeAdvice {
  rule: string;
  value: number | null;
  threshold: number;
  meets: boolean;
  text: string;
}

export interface ResearchTemplateSuggestion {
  key: "prognostic_model" | "risk_factor" | "dose_response" | "longitudinal";
  name: string;
  description: string;
  applicable: boolean;
  reasons: string[];
  task_type: TaskType;
  models: string[];
  charts: string[];
  sample_size: SampleSizeAdvice[];
}

export interface ResearchTemplatesResponse {
  templates: ResearchTemplateSuggestion[];
}

export async function getResearchTemplates(
  datasetId: string,
): Promise<ResearchTemplatesResponse> {
  return apiFetch<ResearchTemplatesResponse>(`/datasets/${datasetId}/research-templates`);
}

// ---- 单因素筛选 + 亚组分析（T6.10；docs/14 §3） ----

export interface UnivariateScreenRow {
  feature: string;
  test: string;
  statistic: number | null;
  effect: number | null;
  p_value: number;
  n_used: number;
  selected: boolean;
}

export interface UnivariateScreenResult {
  task_type: TaskType;
  alpha: number;
  rows: UnivariateScreenRow[];
  selected_features: string[];
}

export interface UnivariateScreenRequest {
  task_type: TaskType;
  label_col?: string;
  time_col?: string;
  event_col?: string;
  features?: string[];
  alpha?: number;
}

export async function univariateScreen(
  datasetId: string,
  body: UnivariateScreenRequest,
): Promise<UnivariateScreenResult> {
  return apiFetch<UnivariateScreenResult>(`/datasets/${datasetId}/univariate-screen`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface SubgroupLevelEffect {
  level: string;
  n: number;
  effect: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  note: string | null;
}

export interface SubgroupResult {
  variable: string;
  levels: SubgroupLevelEffect[];
  interaction_p: number | null;
}

export interface SubgroupAnalysisResult {
  task_type: TaskType;
  exposure: string;
  subgroups: SubgroupResult[];
}

export interface SubgroupAnalysisRequest {
  task_type: TaskType;
  exposure: string;
  subgroup_vars: string[];
  label_col?: string;
  time_col?: string;
  event_col?: string;
}

export async function subgroupAnalysis(
  datasetId: string,
  body: SubgroupAnalysisRequest,
): Promise<SubgroupAnalysisResult> {
  return apiFetch<SubgroupAnalysisResult>(`/datasets/${datasetId}/subgroup-analysis`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---- 分析运行（docs/14 §3 /analysis-runs；docs/08 §3 状态机） ----

export type RunStatus =
  | "PENDING"
  | "PREPROCESSING"
  | "MODELING"
  | "COMPARING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELED";

export type ModelTaskStatus = "PENDING" | "RUNNING" | "SUCCESS" | "FAILED" | "SKIPPED";

export interface AnalysisRun {
  id: string;
  status: RunStatus;
  task_type: TaskType;
  created_at: string;
}

export interface AnalysisRunDetail extends AnalysisRun {
  task_detection: Record<string, unknown> | null;
  error: string | null;
}

export interface RunProgress {
  status: RunStatus;
  percent: number;
  current_step: string | null;
  models: Record<string, ModelTaskStatus>;
  errors: Record<string, string>;
}

export async function listProjectRuns(
  projectId: string,
): Promise<{ items: AnalysisRun[]; next_cursor: string | null }> {
  return apiFetch(`/projects/${projectId}/analysis-runs`);
}

export async function getRun(runId: string): Promise<AnalysisRunDetail> {
  return apiFetch<AnalysisRunDetail>(`/analysis-runs/${runId}`);
}

export async function getRunProgress(runId: string): Promise<RunProgress> {
  return apiFetch<RunProgress>(`/analysis-runs/${runId}/progress`);
}

export async function cancelRun(runId: string): Promise<{ status: string }> {
  return apiFetch(`/analysis-runs/${runId}/cancel`, { method: "POST" });
}

export interface AnalysisRunCreate {
  dataset_version_id: string;
  task_type: TaskType;
  preprocess_config: PreprocessConfig;
  selected_models: string[];
  model_params?: Record<string, Record<string, unknown>>;
}

export async function createRun(body: AnalysisRunCreate): Promise<AnalysisRun> {
  return apiFetch<AnalysisRun>("/analysis-runs", { method: "POST", body: JSON.stringify(body) });
}

/** GET /models?task_type=（docs/14）：启用且支持该任务类型的插件。 */
export async function listModels(taskType: TaskType): Promise<ModelPlugin[]> {
  return apiFetch<ModelPlugin[]>(`/models?task_type=${taskType}`);
}

export async function rerunModel(runId: string, modelKey: string): Promise<{ status: string }> {
  return apiFetch(`/analysis-runs/${runId}/models/${modelKey}/rerun`, { method: "POST" });
}

// ---- T6.13 对话式迭代（docs/14 POST /analysis-runs/{id}/iterate） ----

export interface RerunSuggestion {
  summary: string;
  add_features: string[];
  drop_features: string[];
  selected_models: string[] | null;
}

export interface IterateResponse {
  answer: string;
  suggestion: RerunSuggestion | null;
  llm_enhanced: boolean;
  dataset_id: string;
  project_id: string; // 向导路由所需项目 id
}

export async function iterateRun(runId: string, question: string): Promise<IterateResponse> {
  return apiFetch<IterateResponse>(`/analysis-runs/${runId}/iterate`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

// ---- 比较结果（docs/14 §3 ComparisonResult；docs/09 §5） ----

export interface ModelMetricsRow {
  model_key: string;
  status: ModelTaskStatus;
  metrics: Record<string, { mean: number; std: number; folds?: number[] }> | null;
  error: string | null;
  duration_ms: number | null;
}

export interface ChartAsset {
  kind: string;
  title: string;
  data: Record<string, unknown>;
  image_uri: string | null;
}

export interface RecommendationTop {
  model_key: string;
  rank: number;
  reason: string;
}

export interface Recommendation {
  ranking: string[];
  top: RecommendationTop[];
  not_recommended?: { model_key: string; reason: string }[];
  primary_metric: string;
  formula?: string;
  scores?: { model_key: string; score: number; components: Record<string, number> }[];
}

export interface ComparisonResult {
  table: ModelMetricsRow[];
  ranking: string[];
  recommendation: Recommendation;
  charts: ChartAsset[];
}

export async function getComparison(runId: string): Promise<ComparisonResult> {
  return apiFetch<ComparisonResult>(`/analysis-runs/${runId}/comparison`);
}

// ---- 报告（docs/14 /reports；docs/10 §4 预览与下载） ----

export type ReportFormat = "pdf" | "html" | "markdown" | "docx";
export type ReportStatus = "PENDING" | "READY" | "FAILED";

export interface ReportItem {
  id: string;
  run_id: string;
  status: ReportStatus;
  format: ReportFormat;
  template_key: string;
  created_at: string;
}

export async function createReport(runId: string, format: ReportFormat): Promise<ReportItem> {
  return apiFetch<ReportItem>("/reports", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, format }),
  });
}

export async function listRunReports(runId: string): Promise<ReportItem[]> {
  return apiFetch<ReportItem[]>(`/analysis-runs/${runId}/reports`);
}

/** 下载/预览均经 download 端点（302 → 预签名），需带 Bearer，故 fetch → Blob URL。 */
export async function fetchReportBlob(reportId: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(`${BASE}/reports/${reportId}/download`, {
    headers,
    credentials: "include",
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.blob();
}

export async function downloadReport(report: ReportItem): Promise<void> {
  const blob = await fetchReportBlob(report.id);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report-${report.id.slice(0, 8)}.${report.format}`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---- 插件管理（docs/14 /admin/plugins、/models；docs/15 §1） ----

export interface ModelPlugin {
  key: string;
  name: string;
  version: string;
  task_types: string[];
  capability: Record<string, unknown>;
  enabled: boolean;
  /** T6.12 模型分层：standard=标准套餐（向导默认勾选），advanced=高级选项 */
  tier: "standard" | "advanced";
  /** 标准套餐内角色标注（如 基线·可解释 / 强模型），高级选项为 null */
  role: string | null;
}

export async function listAdminPlugins(): Promise<ModelPlugin[]> {
  return apiFetch<ModelPlugin[]>("/admin/plugins");
}

export async function updateAdminPlugin(
  key: string,
  patch: { enabled?: boolean; default_params?: Record<string, unknown> },
): Promise<ModelPlugin> {
  return apiFetch<ModelPlugin>(`/admin/plugins/${key}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// ---- LLM 设置（docs/14 /admin/settings/llm*；T6.6） ----

export type LlmFeatureSwitch = "off" | "local" | "local_first" | "cloud";
export type LlmModelChoice = "auto" | "local" | "cloud";

export interface LlmProviderStatus {
  available: boolean;
  provider: string | null;
  model: string | null;
  enabled?: boolean | null;
}

export interface LlmSettings {
  status: {
    local: LlmProviderStatus;
    cloud: LlmProviderStatus;
    default_choice: LlmModelChoice;
  };
  config: {
    model_choice: LlmModelChoice;
    temperature: number;
    ollama_model: string;
    cloud_enabled: boolean;
    cloud_has_key: boolean;
    cloud_key_preview: string;
    feature_switches: {
      research_profile: LlmFeatureSwitch;
      report_interpretation: LlmFeatureSwitch;
      validation_explain: LlmFeatureSwitch;
      iteration: LlmFeatureSwitch;
    };
  };
}

export interface LlmSettingsPatch {
  model_choice?: LlmModelChoice;
  temperature?: number;
  ollama_model?: string;
  openai_api_key?: string; // 只写不读；空串清除
  feature_switches?: {
    research_profile: LlmFeatureSwitch;
    report_interpretation: LlmFeatureSwitch;
    validation_explain: LlmFeatureSwitch;
    iteration: LlmFeatureSwitch;
  };
}

export interface LlmTestResult {
  ok: boolean;
  provider: string;
  latency_ms: number;
  detail: string;
}

export async function getLlmSettings(): Promise<LlmSettings> {
  return apiFetch<LlmSettings>("/admin/settings/llm");
}

export async function updateLlmSettings(patch: LlmSettingsPatch): Promise<LlmSettings> {
  return apiFetch<LlmSettings>("/admin/settings/llm", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

export async function testLlmProvider(provider: "local" | "cloud"): Promise<LlmTestResult> {
  return apiFetch<LlmTestResult>("/admin/settings/llm/test", {
    method: "POST",
    body: JSON.stringify({ provider }),
  });
}

export async function listOllamaModels(): Promise<{ available: boolean; models: string[] }> {
  return apiFetch<{ available: boolean; models: string[] }>(
    "/admin/settings/llm/ollama-models",
  );
}

/** 从 access token 解出角色（UI 门控；服务端仍做 RBAC 强校验）。 */
export function getRole(): string | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1])) as { role?: string };
    return payload.role ?? null;
  } catch {
    return null;
  }
}
