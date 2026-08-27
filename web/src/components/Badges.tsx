import type { Risk, Severity } from "../types";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`badge sev-${severity}`}>
      <span className="dot" aria-hidden="true" />
      {severity}
    </span>
  );
}

export function RiskBadge({ risk }: { risk: Risk }) {
  return (
    <span className={`badge sev-${risk}`}>
      <span className="dot" aria-hidden="true" />
      {risk}
    </span>
  );
}

const STATUS_CLASS: Record<string, string> = {
  completed: "status-ok",
  approved: "status-ok",
  executed: "status-ok",
  needs_approval: "status-warn",
  pending: "status-warn",
  pending_approval: "status-warn",
  denied: "status-bad",
  auth_error: "status-bad",
  budget_exceeded: "status-bad",
  step_budget_exceeded: "status-bad",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_CLASS[status] ?? "status-neutral";
  return <span className={`badge ${cls}`}>{status.replace(/_/g, " ")}</span>;
}

export function GroundedBadge({ grounded }: { grounded: boolean }) {
  return (
    <span className={`badge ${grounded ? "status-ok" : "status-bad"}`}>
      {grounded ? "grounded ✓" : "ungrounded ✗"}
    </span>
  );
}
