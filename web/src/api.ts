import type {
  AuditEntry,
  AuditVerify,
  DecideResponse,
  Decision,
  EvalReport,
  Health,
  Role,
  Run,
  Ticket,
  Tool,
  TriageResult,
} from "./types";

const BASE = "/api";

export const ROLE_KEYS: Record<Role, string> = {
  viewer: "demo-viewer-key",
  operator: "demo-operator-key",
  admin: "demo-admin-key",
};

/** Raised when the backend returns a non-2xx response. */
export class ApiError extends Error {
  readonly status: number;
  readonly role: Role;
  constructor(status: number, message: string, role: Role) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.role = role;
  }

  /** True for auth/permission failures (used to show a friendly RBAC note). */
  get isForbidden(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  /** Endpoints `/health` and `/tools` are public and need no key. */
  auth?: boolean;
}

async function request<T>(
  path: string,
  role: Role,
  opts: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, auth = true } = opts;
  const headers: Record<string, string> = {};
  if (auth) headers["X-API-Key"] = ROLE_KEYS[role];
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(
      0,
      "Could not reach the backend. Is it running on :8000 (make serve)?",
      role,
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data && typeof data.detail === "string") detail = data.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail, role);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: (role: Role) =>
    request<Health>("/health", role, { auth: false }),
  tools: (role: Role) => request<Tool[]>("/tools", role, { auth: false }),

  tickets: (role: Role) => request<Ticket[]>("/tickets", role),
  ticket: (role: Role, id: string) =>
    request<Ticket>(`/tickets/${encodeURIComponent(id)}`, role),

  triage: (role: Role, id: string) =>
    request<TriageResult>(`/triage/${encodeURIComponent(id)}`, role, {
      method: "POST",
    }),

  runs: (role: Role) => request<Run[]>("/runs", role),
  run: (role: Role, runId: string) =>
    request<Run>(`/runs/${encodeURIComponent(runId)}`, role),

  approvals: (role: Role, status = "pending") =>
    request<Decision[]>(
      `/approvals?status=${encodeURIComponent(status)}`,
      role,
    ),
  decide: (role: Role, approvalId: string, approve: boolean, reason?: string) =>
    request<DecideResponse>(
      `/approvals/${encodeURIComponent(approvalId)}/decide`,
      role,
      { method: "POST", body: { approve, reason } },
    ),

  audit: (role: Role) => request<AuditEntry[]>("/audit", role),
  auditVerify: (role: Role) => request<AuditVerify>("/audit/verify", role),

  evalsLatest: (role: Role) => request<EvalReport>("/evals/latest", role),
};
