export type ResourceItem = {
  type: "service" | "agent";
  id: string;
  name: string;
  kind: string;
  status: string;
  group_id: string | null;
  detail: string | null;
  children: number;
};

export type ResourceGroup = {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  created_at: string;
  resources: ResourceItem[];
};

export type Inventory = {
  groups: ResourceGroup[];
  standalone: ResourceItem[];
  counts: { groups: number; services: number; agents: number };
};

export type Service = {
  id: string;
  name: string;
  kind: string;
  endpoint: string | null;
  auth_type: string;
  credential_policy: string;
  resource_group_id: string | null;
  status: string;
  runtime_requirements: Record<string, unknown>;
  manifest_hash: string | null;
  manifest_synced_at: string | null;
  created_at: string;
};

export type Agent = {
  id: string;
  slug: string;
  name: string;
  kind: string;
  status: string;
  ceiling: Record<string, unknown>;
  resource_group_id: string | null;
  created_at: string;
};

export type Grant = {
  id: string;
  agent_id: string;
  service_id: string;
  tools: string[];
  arg_constraints: Record<string, unknown>;
  status: string;
  expires_at: string | null;
  updated_at: string;
};

export type CredentialCreated = {
  id: string;
  type: string;
  api_key: string | null;
  prefix: string | null;
  expires_at: string | null;
};

export type Tool = {
  id: string;
  name: string;
  description: string | null;
  input_schema: Record<string, unknown>;
  annotations: Record<string, unknown>;
  definition_hash: string;
  last_seen_at: string;
};

export type Connection = {
  id: string;
  agent_id: string | null;
  user_id: string | null;
  service_id: string;
  binding: string;
  status: string;
  scopes: string[];
  expires_at: string | null;
};

export type Identity = {
  kind: "user" | "agent";
  id: string;
  name: string;
  email: string | null;
  role: string;
  permissions: string[];
  status: string;
  agent_kind: string | null;
  group_count: number;
  grant_count: number;
  last_seen_at: string | null;
  identity_id: string | null;
  identity_name: string | null;
  is_identity_admin: boolean;
};

export type IdentityEntity = {
  kind: "user" | "agent";
  id: string;
  name: string;
  email: string | null;
  role: string;
  permissions: string[];
  status: string;
  is_identity_admin: boolean;
  agent_kind: string | null;
  group_count: number;
  grant_count: number;
  last_seen_at: string | null;
};

export type IdentityGroup = {
  id: string;
  name: string;
  status: string;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
  entities: IdentityEntity[];
  signup_id: string | null;
  requested_role: string | null;
  owner_email: string | null;
  can_manage: boolean;
};

export type IdentityInviteCreated = {
  id: string;
  identity_id: string;
  identity_name: string;
  email: string;
  role: string;
  invite_url: string;
  expires_at: string;
};

export type IdentityInvitePreview = {
  identity_name: string;
  workspace_slug: string;
  workspace_name: string;
  email: string;
  role: string;
  expires_at: string;
};

export type IdentityInviteAccepted = {
  token: string;
  token_type: string;
  expires_in: number;
  workspace_slug: string;
  identity_id: string;
  identity_name: string;
  user: {
    id: string;
    email: string;
    display_name: string | null;
  };
};

export type SignupRequest = {
  id: string;
  kind: "user" | "agent";
  status: "pending" | "approved" | "rejected";
  identity_id: string | null;
  identity_name: string | null;
  email: string | null;
  owner_email: string | null;
  display_name: string | null;
  agent_name: string | null;
  agent_slug: string | null;
  requested_role: string | null;
  message: string | null;
  principal_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
};

export type SignupCreate = {
  kind: "user" | "agent";
  email?: string;
  display_name?: string;
  agent_name?: string;
  agent_slug?: string;
  identity_name?: string;
  owner_email?: string;
  password?: string;
  requested_role?: string;
  message?: string;
};

export type SignupDecision = {
  request: SignupRequest;
  credential: CredentialCreated | null;
};

export type TraceSpan = {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  status: string;
  duration_ms: number;
  actor_type: string | null;
  actor_id: string | null;
  attributes: Record<string, unknown>;
  started_at: string;
};

export type TraceSummary = {
  trace_id: string;
  root_name: string;
  status: string;
  duration_ms: number;
  span_count: number;
  actor_type: string | null;
  actor_id: string | null;
  started_at: string;
};

export type TraceDetail = { trace_id: string; spans: TraceSpan[] };

export type AuditEvent = {
  id: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  decision: string | null;
  reason: string | null;
  trace_id: string;
  meta: Record<string, unknown>;
  created_at: string;
};

export type Me = {
  kind: "user" | "agent";
  id: string;
  workspace_id: string;
  workspace_slug: string | null;
  role: string;
  permissions: string[];
  agent_id: string | null;
  email: string | null;
  identity_id: string | null;
  identity_name: string | null;
  is_identity_admin: boolean;
};

const TOKEN_KEY = "agw.token";
const WORKSPACE_KEY = "agw.workspace";
const EMAIL_KEY = "agw.email";
const SESSION_EXPIRED_KEY = "agw.session-expired";

export class ApiError extends Error {
  status: number;
  traceId?: string;

  constructor(message: string, status: number, traceId?: string) {
    super(message);
    this.status = status;
    this.traceId = traceId;
  }
}

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, workspace: string, email = ""): void {
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(WORKSPACE_KEY, workspace);
  sessionStorage.setItem(EMAIL_KEY, email);
}

export function getWorkspace(): string {
  return sessionStorage.getItem(WORKSPACE_KEY) ?? "";
}

export function getEmail(): string {
  return sessionStorage.getItem(EMAIL_KEY) ?? "";
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(WORKSPACE_KEY);
  sessionStorage.removeItem(EMAIL_KEY);
}

export function consumeSessionExpired(): boolean {
  const expired = sessionStorage.getItem(SESSION_EXPIRED_KEY) === "1";
  if (expired) sessionStorage.removeItem(SESSION_EXPIRED_KEY);
  return expired;
}

async function request(path: string, init: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    if (
      response.status === 401 &&
      token &&
      !path.startsWith("/v1/auth/") &&
      !path.startsWith("/v1/bootstrap")
    ) {
      clearSession();
      sessionStorage.setItem(SESSION_EXPIRED_KEY, "1");
      window.location.assign("/");
    }
    const traceId = response.headers.get("x-trace-id") ?? undefined;
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.message || body.error || message;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(message, response.status, traceId);
  }
  return response;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await request(path, init);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type Page<T> = {
  items: T[];
  total: number;
  snapshot: string | null;
};

export async function apiPage<T>(
  path: string,
  init: RequestInit = {},
): Promise<Page<T>> {
  const response = await request(path, init);
  const total = Number(response.headers.get("x-total-count") ?? 0);
  return {
    items: (await response.json()) as T[],
    total: Number.isFinite(total) ? total : 0,
    snapshot: response.headers.get("x-snapshot"),
  };
}

export type AuthConfig = {
  password: boolean;
  google: boolean;
  dev: boolean;
};

export async function getAuthConfig(): Promise<AuthConfig> {
  return api("/v1/auth/config");
}

export async function login(
  workspace: string,
  email: string,
  password: string,
): Promise<{ token: string; expires_in: number }> {
  return api("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({
      workspace_slug: workspace,
      email,
      password,
    }),
  });
}

export function googleLoginUrl(workspace: string, next = "/"): string {
  const params = new URLSearchParams({
    workspace_slug: workspace,
    next,
  });
  return `/v1/auth/oidc/google/start?${params.toString()}`;
}

export async function requestSignup(
  workspace: string,
  body: SignupCreate,
): Promise<SignupRequest> {
  return api(`/v1/workspaces/${workspace}/signup`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export const fmtDate = (value: string | null | undefined): string => {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const fmtDuration = (ms: number): string => {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
};

export const titleCase = (value: string): string =>
  value
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
