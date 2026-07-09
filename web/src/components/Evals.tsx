import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { EvalReport, Role } from "../types";
import { Card, EmptyState, ErrorNote, Spinner } from "./Common";

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function MetricCard({
  label,
  value,
  good,
}: {
  label: string;
  value: string;
  good?: boolean;
}) {
  return (
    <div className={`eval-card${good === false ? " eval-card-warn" : ""}`}>
      <div className="eval-value">{value}</div>
      <div className="eval-label">{label}</div>
    </div>
  );
}

function Tick({ ok }: { ok: boolean }) {
  return (
    <span className={ok ? "tick-ok" : "tick-bad"}>{ok ? "✓" : "✗"}</span>
  );
}

export function Evals({ role }: { role: Role }) {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let live = true;
    setReport(null);
    setError(null);
    setNotFound(false);
    api
      .evalsLatest(role)
      .then((r) => live && setReport(r))
      .catch((e) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e);
      });
    return () => {
      live = false;
    };
  }, [role]);

  if (notFound) {
    return (
      <Card title="Evals">
        <EmptyState>
          No eval report yet. Run <code className="mono">make eval</code> to
          generate one.
        </EmptyState>
      </Card>
    );
  }

  if (error) {
    return (
      <Card title="Evals">
        <ErrorNote error={error} role={role} />
      </Card>
    );
  }

  if (!report) {
    return (
      <Card title="Evals">
        <Spinner label="Loading eval report…" />
      </Card>
    );
  }

  const m = report.metrics;

  return (
    <div className="evals">
      <Card
        title="Eval report"
        actions={
          <span className="eval-provider">
            <span className="mono">{report.provider}</span> ·{" "}
            <span className="mono">{report.model}</span> · prompt{" "}
            <span className="mono">{report.prompt_version}</span>
          </span>
        }
      >
        <p className="hint">
          Generated {report.timestamp} · {m.n} scenarios
        </p>
        <div className="eval-grid">
          <MetricCard
            label="Classification acc."
            value={pct(m.classification_accuracy)}
          />
          <MetricCard label="Severity acc." value={pct(m.severity_accuracy)} />
          <MetricCard label="Action acc." value={pct(m.action_accuracy)} />
          <MetricCard label="Grounding rate" value={pct(m.grounding_rate)} />
          <MetricCard
            label="Approval safety"
            value={pct(m.approval_safety)}
            good={m.approval_safety >= 1}
          />
          {typeof m.injection_defense === "number" && (
            <MetricCard
              label="Injection defense"
              value={pct(m.injection_defense)}
              good={m.injection_defense >= 1}
            />
          )}
          <MetricCard
            label="Pass rate"
            value={pct(m.pass_rate)}
            good={m.pass_rate >= 0.8}
          />
          <MetricCard
            label="p95 latency"
            value={`${Math.round(m.p95_latency_ms)} ms`}
          />
          <MetricCard label="Avg cost" value={`$${m.avg_usd.toFixed(4)}`} />
        </div>
      </Card>

      <Card title="Scenarios">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Expected (cat / sev / action)</th>
                <th>Predicted (cat / sev / action)</th>
                <th>Grounded</th>
                <th>Gated</th>
                <th>Passed</th>
              </tr>
            </thead>
            <tbody>
              {report.scenarios.map((s) => (
                <tr key={s.id} className={s.passed ? "" : "row-fail"}>
                  <td className="mono">{s.id}</td>
                  <td className="cell-sub">
                    {s.expected.category} / {s.expected.severity} /{" "}
                    {s.expected.action}
                  </td>
                  <td className="cell-sub">
                    {s.predicted.category} / {s.predicted.severity} /{" "}
                    {s.predicted.action}
                    <span className="cell-faint"> ({s.predicted.action_status})</span>
                  </td>
                  <td>
                    <Tick ok={s.grounded} />
                  </td>
                  <td>
                    <Tick ok={s.gated_correctly} />
                  </td>
                  <td>
                    <Tick ok={s.passed} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
