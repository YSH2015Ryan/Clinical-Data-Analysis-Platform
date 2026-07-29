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
  if (init.body && !headers.has("Content-Type")) {
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
