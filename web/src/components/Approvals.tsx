import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { DecideResponse, Decision, Role } from "../types";
import { RiskBadge, StatusBadge } from "./Badges";
import { Card, EmptyState, ErrorNote, Spinner } from "./Common";

const POLL_MS = 5000;

function ApprovalRow({
  decision,
  role,
  onDecided,
}: {
  decision: Decision;
  role: Role;
  onDecided: (res: DecideResponse) => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const isAdmin = role === "admin";

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.decide(
        role,
        decision.approval_id,
        approve,
        reason.trim() || undefined,
      );
      onDecided(res);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="approval">
      <div className="approval-head">
        <div>
          <span className="approval-action mono">{decision.action}</span>
          <span className="approval-by">requested by {decision.requested_by}</span>
        </div>
        <RiskBadge risk={decision.risk} />
      </div>

      {Object.keys(decision.args).length > 0 && (
        <pre className="json-block">{JSON.stringify(decision.args, null, 2)}</pre>
      )}

      {error != null && <ErrorNote error={error} role={role} />}

      {isAdmin ? (
        <div className="approval-actions">
          <label className="field">
            <span className="sr-only">Reason (optional)</span>
            <input
              type="text"
              className="input"
              placeholder="Reason (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
            />
          </label>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy}
            onClick={() => decide(true)}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            disabled={busy}
            onClick={() => decide(false)}
          >
            Deny
          </button>
        </div>
      ) : (
        <p className="hint">
          Deciding approvals requires the <strong>admin</strong> role. Switch
          roles using the dropdown above.
        </p>
      )}
    </div>
  );
}

export function Approvals({ role }: { role: Role }) {
  const [pending, setPending] = useState<Decision[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lastResult, setLastResult] = useState<DecideResponse | null>(null);

  const load = useCallback(
    async (silent: boolean) => {
      if (!silent) {
        setPending(null);
        setError(null);
      }
      try {
        const list = await api.approvals(role, "pending");
        setPending(list);
        setError(null);
      } catch (e) {
        if (!silent) setError(e);
      }
    },
    [role],
  );

  useEffect(() => {
    load(false);
    const id = window.setInterval(() => load(true), POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  function handleDecided(res: DecideResponse) {
    setLastResult(res);
    load(true);
  }

  return (
    <Card
      title="Pending approvals"
      actions={
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => load(false)}
        >
          Refresh
        </button>
      }
    >
      {lastResult && (
        <div className="callout callout-ok" role="status">
          <strong>Decision recorded.</strong> Approval{" "}
          <span className="mono">{lastResult.decision.approval_id}</span> is now{" "}
          <StatusBadge status={lastResult.decision.status} />.
          {lastResult.execution && (
            <>
              {" "}
              Execution: <StatusBadge status={lastResult.execution.status} /> for{" "}
              <span className="mono">{lastResult.execution.action}</span>.
            </>
          )}
        </div>
      )}

      {error ? (
        <ErrorNote error={error} role={role} />
      ) : pending === null ? (
        <Spinner label="Loading approvals…" />
      ) : pending.length === 0 ? (
        <EmptyState>
          No pending approvals. Run triage on a high-risk ticket to generate
          one.
        </EmptyState>
      ) : (
        <div className="approval-list">
          {pending.map((d) => (
            <ApprovalRow
              key={d.approval_id}
              decision={d}
              role={role}
              onDecided={handleDecided}
            />
          ))}
        </div>
      )}
      <p className="hint">Auto-refreshes every {POLL_MS / 1000}s.</p>
    </Card>
  );
}
