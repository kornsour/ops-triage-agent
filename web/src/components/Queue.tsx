import { useEffect, useState } from "react";
import { api } from "../api";
import type { Role, Ticket } from "../types";
import { SeverityBadge, StatusBadge } from "./Badges";
import { Card, EmptyState, ErrorNote, Spinner } from "./Common";

export function Queue({
  role,
  onRunComplete,
}: {
  role: Role;
  onRunComplete: (runId: string) => void;
}) {
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runError, setRunError] = useState<unknown>(null);

  const canTriage = role === "operator" || role === "admin";

  useEffect(() => {
    let live = true;
    setTickets(null);
    setError(null);
    api
      .tickets(role)
      .then((t) => live && setTickets(t))
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, [role]);

  async function runTriage(id: string) {
    setRunningId(id);
    setRunError(null);
    try {
      const result = await api.triage(role, id);
      onRunComplete(result.run_id);
    } catch (e) {
      setRunError(e);
    } finally {
      setRunningId(null);
    }
  }

  return (
    <Card title="Ticket queue">
      {runError != null && <ErrorNote error={runError} role={role} />}
      {error ? (
        <ErrorNote error={error} role={role} />
      ) : tickets === null ? (
        <Spinner label="Loading tickets…" />
      ) : tickets.length === 0 ? (
        <EmptyState>No tickets in the queue.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Subject</th>
                <th>Requester</th>
                <th>Severity</th>
                <th>Status</th>
                <th className="col-action" />
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.id}>
                  <td className="mono">{t.id}</td>
                  <td>
                    <div className="cell-primary">{t.subject}</div>
                    <div className="cell-sub">{t.category}</div>
                  </td>
                  <td>{t.requester}</td>
                  <td>
                    <SeverityBadge severity={t.severity} />
                  </td>
                  <td>
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="col-action">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={!canTriage || runningId !== null}
                      title={
                        canTriage
                          ? "Run the triage agent on this ticket"
                          : "Requires the operator or admin role"
                      }
                      onClick={() => runTriage(t.id)}
                    >
                      {runningId === t.id ? "Running…" : "Run triage"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!canTriage && tickets && tickets.length > 0 && (
        <p className="hint">
          Running triage requires the <strong>operator</strong> or{" "}
          <strong>admin</strong> role.
        </p>
      )}
    </Card>
  );
}
