/** API 客户端：契约同源 docs/14（/api/v1，Bearer JWT，RFC7807 错误）。 */

const BASE = "/api/v1";
const TOKEN_KEY = "cdap_access_token";
const REFRESH_KEY = "cdap_refresh_token";

export interface ApiError {
  code: string;
  message: string;
  details: Record<string, unknown>;
  trace_id: string;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

async function parseError(resp: Response): Promise<ApiError> {
  try {
    return (await resp.json()) as ApiError;
  } catch {
    return { code: "INTERNAL_ERROR", message: `HTTP ${resp.status}`, details: {}, trace_id: "" };
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!resp.ok) {
    const err = await parseError(resp);
    if (resp.status === 401 && getToken()) {
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

export async function uploadDataset(projectId: string, file: File): Promise<{ dataset_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<{ dataset_id: string }>(`/projects/${projectId}/datasets`, {
    method: "POST",
    body: form,
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
  type: "drop_column" | "drop_duplicates" | "to_missing" | "remap_semantic";
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

export const SEMANTIC_OPTIONS = ["Age", "Gender", "Diagnosis", "FollowUp", "Event", "Label"];

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
