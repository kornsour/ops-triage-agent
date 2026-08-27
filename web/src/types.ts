// Typed mirrors of the FastAPI backend contract (base URL /api).

export type Role = "viewer" | "operator" | "admin";

export type Severity = "low" | "medium" | "high";
export type Risk = "low" | "medium" | "high";

export interface Health {
  status: string;
  provider: string;
  tickets: number;
  runbooks: number;
}

export type ToolKind = "read" | "action";

export interface Tool {
  name: string;
  kind: ToolKind;
  description: string;
  params: Record<string, unknown>;
}

export interface Ticket {
  id: string;
  subject: string;
  body: string;
  requester: string;
  status: string;
  category: string;
  severity: Severity;
  created_at: string;
}

export type TriageStatus =
  | "completed"
  | "ungrounded"
  | "needs_approval"
  | "denied"
  | "auth_error"
  | "budget_exceeded"
  | "step_budget_exceeded"
  // The sandbox boundary (see docs/sandbox.md), not the approval policy, is
  // why the recommended action didn't execute: timed out, was killed, or
  // was denied before it ran.
  | "action_contained";

export type ActionStatus = string;

export interface TriageAction {
  name: string;
  status: ActionStatus;
  args?: Record<string, unknown>;
  approval_id?: string;
  risk?: Risk;
  result?: unknown;
  reason?: string | null;
}

export interface TriageMetrics {
  total_ms: number;
  steps_ms: Record<string, number>;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  usd: number;
  llm_calls: number;
}

export interface TraceStep {
  step: string;
  ms: number;
  detail: Record<string, unknown>;
}

export interface TriageResult {
  run_id: string;
  ticket_id: string;
  status: TriageStatus;
  category: string;
  severity: Severity;
  summary: string;
  plan: string[];
  draft_reply: string;
  citations: string[];
  confidence: number;
  grounded: boolean;
  action: TriageAction;
  metrics: TriageMetrics;
  trace: TraceStep[];
  prompt_version: string;
  injection_detected: boolean;
  injection_signals: string[];
}

export interface Run {
  run_id: string;
  ticket_id: string;
  status: string;
  result: TriageResult;
  created_at: string;
}

export type DecisionStatus = "pending" | "approved" | "denied" | "executed";

export interface Decision {
  approval_id: string;
  status: DecisionStatus;
  action: string;
  args: Record<string, unknown>;
  risk: Risk;
  requested_by: string;
  decided_by: string | null;
  reason: string | null;
}

export interface Execution {
  status: string;
  action: string;
  result: unknown;
}

export interface DecideResponse {
  decision: Decision;
  execution?: Execution;
}

export interface AuditEntry {
  seq: number;
  ts: string;
  actor: string;
  action: string;
  target: string;
  outcome: string;
  metadata: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface AuditVerify {
  ok: boolean;
  message: string;
  entries: number;
}

export interface EvalMetrics {
  n: number;
  classification_accuracy: number;
  severity_accuracy: number;
  action_accuracy: number;
  grounding_rate: number;
  approval_safety: number;
  injection_defense: number;
  pass_rate: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  avg_usd: number;
}

export interface EvalScenario {
  id: string;
  expected: { category: string; severity: string; action: string };
  predicted: {
    category: string;
    severity: string;
    action: string;
    action_status: string;
  };
  grounded: boolean;
  gated_correctly: boolean;
  passed: boolean;
}

export interface EvalReport {
  timestamp: string;
  provider: string;
  model: string;
  prompt_version: string;
  metrics: EvalMetrics;
  scenarios: EvalScenario[];
}
