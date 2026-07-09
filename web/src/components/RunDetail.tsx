import { useEffect, useState } from "react";
import { api } from "../api";
import type { Role, TraceStep, TriageResult } from "../types";
import {
  GroundedBadge,
  SeverityBadge,
  StatusBadge,
} from "./Badges";
import { Card, EmptyState, ErrorNote, KeyVal, Spinner } from "./Common";

function summarizeDetail(detail: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(detail)) {
    if (v === null || v === undefined) continue;
    let text: string;
    if (Array.isArray(v)) text = `${v.length} item${v.length === 1 ? "" : "s"}`;
    else if (typeof v === "object") text = JSON.stringify(v);
    else text = String(v);
    if (text.length > 80) text = `${text.slice(0, 77)}…`;
    parts.push(`${k}: ${text}`);
  }
  return parts.join(" · ");
}

function TraceTimeline({ trace }: { trace: TraceStep[] }) {
  if (trace.length === 0) return <EmptyState>No trace recorded.</EmptyState>;
  return (
    <ol className="timeline">
      {trace.map((step, i) => (
        <li key={`${step.step}-${i}`} className="timeline-item">
          <div className="timeline-marker" aria-hidden="true">
            <span className="timeline-dot" />
            {i < trace.length - 1 && <span className="timeline-line" />}
          </div>
          <div className="timeline-body">
            <div className="timeline-head">
              <span className="timeline-step">{step.step}</span>
              <span className="timeline-ms mono">{step.ms} ms</span>
            </div>
            {Object.keys(step.detail).length > 0 && (
              <div className="timeline-detail">{summarizeDetail(step.detail)}</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ResultView({ result, role }: { result: TriageResult; role: Role }) {
  const { action, metrics } = result;
  const awaitingApproval =
    action.status === "pending_approval" || result.status === "needs_approval";

  return (
    <div className="run-detail">
      <Card
        title={
          <span className="run-title">
            Run <span className="mono">{result.run_id}</span>
          </span>
        }
        actions={<StatusBadge status={result.status} />}
      >
        <div className="run-meta">
          <KeyVal k="ticket" v={<span className="mono">{result.ticket_id}</span>} />
          <KeyVal k="category" v={result.category} />
          <KeyVal k="severity" v={<SeverityBadge severity={result.severity} />} />
          <KeyVal
            k="confidence"
            v={`${Math.round(result.confidence * 100)}%`}
          />
          <KeyVal k="grounded" v={<GroundedBadge grounded={result.grounded} />} />
          <KeyVal
            k="prompt"
            v={<span className="mono">{result.prompt_version}</span>}
          />
        </div>
        <p className="run-summary">{result.summary}</p>
      </Card>

      {result.injection_detected && (
        <div className="callout callout-warn" role="status">
          <strong>Prompt-injection attempt detected.</strong> The ticket contained
          text trying to steer the agent past its controls
          {result.injection_signals.length > 0 && (
            <>
              {" "}
              (
              {result.injection_signals.map((s, i) => (
                <span key={s}>
                  {i > 0 ? ", " : ""}
                  <span className="mono">{s}</span>
                </span>
              ))}
              )
            </>
          )}
          . Triage still ran, but every action from this run is forced through
          human approval — nothing auto-executes off tainted input.
        </div>
      )}

      {awaitingApproval && (
        <div className="callout callout-warn" role="status">
          <strong>Awaiting admin approval.</strong> This run proposed a{" "}
          {action.risk ? <span>{action.risk}-risk </span> : null}action
          {action.name ? (
            <>
              {" "}
              (<span className="mono">{action.name}</span>)
            </>
          ) : null}{" "}
          that is gated behind a human approval. Switch to the{" "}
          <strong>admin</strong> role and visit <strong>Approvals</strong> to
          decide.
          {action.approval_id && (
            <>
              {" "}
              Approval ID: <span className="mono">{action.approval_id}</span>
            </>
          )}
        </div>
      )}

      <div className="grid-2">
        <Card title="Plan">
          {result.plan.length === 0 ? (
            <EmptyState>No plan steps.</EmptyState>
          ) : (
            <ol className="plan-list">
              {result.plan.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Trace">
          <TraceTimeline trace={result.trace} />
        </Card>
      </div>

      <Card title="Draft reply">
        <pre className="draft-reply">{result.draft_reply}</pre>
        {result.citations.length > 0 && (
          <div className="chips">
            {result.citations.map((c, i) => (
              <span key={i} className="chip mono" title={c}>
                {c}
              </span>
            ))}
          </div>
        )}
      </Card>

      <Card title="Proposed action">
        <div className="run-meta">
          <KeyVal k="name" v={<span className="mono">{action.name || "—"}</span>} />
          <KeyVal k="status" v={<StatusBadge status={action.status} />} />
          {action.risk && (
            <KeyVal k="risk" v={<StatusBadge status={action.risk} />} />
          )}
          {action.approval_id && (
            <KeyVal
              k="approval"
              v={<span className="mono">{action.approval_id}</span>}
            />
          )}
        </div>
        {action.args && Object.keys(action.args).length > 0 && (
          <pre className="json-block">
            {JSON.stringify(action.args, null, 2)}
          </pre>
        )}
      </Card>

      <Card title="Metrics">
        <div className="metric-row">
          <Metric label="Total" value={`${metrics.total_ms} ms`} />
          <Metric label="Tokens" value={metrics.total_tokens.toLocaleString()} />
          <Metric label="Input" value={metrics.input_tokens.toLocaleString()} />
          <Metric
            label="Output"
            value={metrics.output_tokens.toLocaleString()}
          />
          <Metric label="Cost" value={`$${metrics.usd.toFixed(4)}`} />
          <Metric label="LLM calls" value={String(metrics.llm_calls)} />
        </div>
      </Card>

      <p className="hint">
        Role context: viewing as <strong>{role}</strong>.
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

export function RunDetail({
  role,
  runId,
}: {
  role: Role;
  runId: string | null;
}) {
  const [result, setResult] = useState<TriageResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!runId) {
      setResult(null);
      setError(null);
      return;
    }
    let live = true;
    setResult(null);
    setError(null);
    api
      .run(role, runId)
      .then((r) => live && setResult(r.result))
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, [role, runId]);

  if (!runId) {
    return (
      <Card title="Run detail">
        <EmptyState>
          Select a ticket in the <strong>Queue</strong> tab and click{" "}
          <strong>Run triage</strong> to see the agent trace here.
        </EmptyState>
      </Card>
    );
  }

  if (error) {
    return (
      <Card title="Run detail">
        <ErrorNote error={error} role={role} />
      </Card>
    );
  }

  if (!result) {
    return (
      <Card title="Run detail">
        <Spinner label="Loading run…" />
      </Card>
    );
  }

  return <ResultView result={result} role={role} />;
}
