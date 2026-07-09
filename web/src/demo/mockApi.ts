// In-browser mock backend for the static GitHub Pages demo.
//
// The React app talks to `/api/*` in normal use. When built with VITE_DEMO=1
// (see api.ts), it uses this instead: the same method surface, backed by
// fixtures generated from the real backend (web/scripts/gen_fixtures.py). No
// server required — approvals mutate in-memory so the approve/deny flow is live.

import { ApiError } from "../apiError";
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
} from "../types";
import fixtures from "./fixtures.json";

interface Fixtures {
  health: Health;
  tools: Tool[];
  tickets: Ticket[];
  runsByTicket: Record<string, string>;
  runs: Run[];
  runDetail: Record<string, Run>;
  approvals: Decision[];
  audit: AuditEntry[];
  auditVerify: AuditVerify;
  evals: EvalReport;
}

const F = fixtures as unknown as Fixtures;

// Mutable copies so interactive actions (approve/deny) persist within a session.
const approvals: Decision[] = structuredClone(F.approvals);
const audit: AuditEntry[] = structuredClone(F.audit);

// Simulate a little network latency so the UI's loading states are visible.
function delay<T>(value: T, ms = 180): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

function requireRole(role: Role, need: Role): void {
  const rank: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };
  if (rank[role] < rank[need]) {
    throw new ApiError(403, `role '${role}' cannot do this (needs '${need}')`, role);
  }
}

function effectFor(action: string, args: Record<string, unknown>): unknown {
  switch (action) {
    case "reset_password":
      return { effect: "password_reset_link_sent", email: args.email, lockout_cleared: true };
    case "grant_access":
      return { effect: "access_granted", email: args.email, resource: args.resource };
    case "escalate":
      return { effect: "escalated", ticket_id: args.ticket_id, team: args.team };
    default:
      return { effect: "applied" };
  }
}

export const mockApi = {
  health: (_role: Role) => delay(F.health),
  tools: (_role: Role) => delay(F.tools),

  tickets: (_role: Role) => delay(F.tickets),
  ticket: (_role: Role, id: string) =>
    delay(F.tickets.find((t) => t.id === id) as Ticket),

  triage: (role: Role, id: string): Promise<TriageResult> => {
    requireRole(role, "operator");
    const runId = F.runsByTicket[id];
    return delay(F.runDetail[runId].result, 420);
  },

  runs: (_role: Role) => delay(F.runs),
  run: (_role: Role, runId: string) => delay(F.runDetail[runId] as Run),

  approvals: (_role: Role, status = "pending") =>
    delay(approvals.filter((a) => a.status === status)),

  decide: (
    role: Role,
    approvalId: string,
    approve: boolean,
    reason?: string,
  ): Promise<DecideResponse> => {
    requireRole(role, "admin");
    const decision = approvals.find((a) => a.approval_id === approvalId);
    if (!decision) {
      throw new ApiError(404, "approval not found", role);
    }
    decision.status = approve ? "executed" : "denied";
    decision.decided_by = "demo-admin";
    decision.reason = reason ?? null;
    audit.push({
      seq: audit.length,
      ts: new Date().toISOString(),
      actor: "demo-admin",
      action: decision.action,
      target: JSON.stringify(decision.args),
      outcome: approve ? "executed" : "denied",
      metadata: { approval_id: approvalId, risk: decision.risk },
      prev_hash: audit.length ? audit[audit.length - 1].hash : "0".repeat(64),
      hash: `demo${audit.length}`,
    });
    const out: DecideResponse = { decision };
    if (approve) {
      out.execution = {
        status: "executed",
        action: decision.action,
        result: effectFor(decision.action, decision.args),
      };
    }
    return delay(out, 300);
  },

  audit: (_role: Role) => delay(audit),
  auditVerify: (_role: Role) =>
    delay({ ok: true, message: "audit chain intact", entries: audit.length }),

  evalsLatest: (_role: Role) => delay(F.evals),
};
