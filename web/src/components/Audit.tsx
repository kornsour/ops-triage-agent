import { useEffect, useState } from "react";
import { api } from "../api";
import type { AuditEntry, AuditVerify, Role } from "../types";
import { Card, EmptyState, ErrorNote, Spinner } from "./Common";

function trunc(hash: string): string {
  return hash ? hash.slice(0, 12) : "—";
}

export function Audit({ role }: { role: Role }) {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [verify, setVerify] = useState<AuditVerify | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let live = true;
    setEntries(null);
    setVerify(null);
    setError(null);
    Promise.all([api.audit(role), api.auditVerify(role)])
      .then(([e, v]) => {
        if (!live) return;
        setEntries(e);
        setVerify(v);
      })
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, [role]);

  return (
    <Card
      title="Audit log"
      actions={
        verify && (
          <span
            className={`chain-badge ${verify.ok ? "chain-ok" : "chain-bad"}`}
            title={verify.message}
          >
            {verify.ok ? "Chain verified ✓" : "Chain BROKEN ✗"}
          </span>
        )
      }
    >
      {error ? (
        <ErrorNote error={error} role={role} />
      ) : entries === null ? (
        <Spinner label="Loading audit log…" />
      ) : entries.length === 0 ? (
        <EmptyState>No audit entries yet.</EmptyState>
      ) : (
        <>
          {verify && (
            <p className="hint">
              {verify.message} ({verify.entries} entries)
            </p>
          )}
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Seq</th>
                  <th>Timestamp</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Outcome</th>
                  <th>Hash</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.seq}>
                    <td className="mono">{e.seq}</td>
                    <td className="mono cell-sub">{e.ts}</td>
                    <td>{e.actor}</td>
                    <td className="mono">{e.action}</td>
                    <td className="mono cell-sub">{e.target}</td>
                    <td>{e.outcome}</td>
                    <td
                      className="mono cell-sub"
                      title={`hash: ${e.hash}\nprev: ${e.prev_hash}`}
                    >
                      {trunc(e.hash)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}
