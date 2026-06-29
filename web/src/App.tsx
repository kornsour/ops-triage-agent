import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health, Role } from "./types";
import { Approvals } from "./components/Approvals";
import { Audit } from "./components/Audit";
import { Evals } from "./components/Evals";
import { Queue } from "./components/Queue";
import { RunDetail } from "./components/RunDetail";

type Tab = "queue" | "run" | "approvals" | "audit" | "evals";

const TABS: { id: Tab; label: string }[] = [
  { id: "queue", label: "Queue" },
  { id: "run", label: "Run Detail" },
  { id: "approvals", label: "Approvals" },
  { id: "audit", label: "Audit" },
  { id: "evals", label: "Evals" },
];

const ROLES: Role[] = ["viewer", "operator", "admin"];
const ROLE_KEY = "ots.role";

function loadRole(): Role {
  const stored = localStorage.getItem(ROLE_KEY);
  if (stored === "viewer" || stored === "operator" || stored === "admin") {
    return stored;
  }
  return "operator";
}

function HealthPill({ role }: { role: Role }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [ok, setOk] = useState(true);

  useEffect(() => {
    let live = true;
    api
      .health(role)
      .then((h) => {
        if (!live) return;
        setHealth(h);
        setOk(true);
      })
      .catch(() => live && setOk(false));
    return () => {
      live = false;
    };
  }, [role]);

  if (!ok) {
    return (
      <div className="health health-down" title="Backend unreachable">
        <span className="health-dot" />
        backend offline
      </div>
    );
  }
  if (!health) {
    return (
      <div className="health">
        <span className="health-dot" />
        checking…
      </div>
    );
  }
  return (
    <div className="health" title={`status: ${health.status}`}>
      <span className="health-dot health-up" />
      <span className="mono">{health.provider}</span>
      <span className="health-sep">·</span>
      {health.tickets} tickets
      <span className="health-sep">·</span>
      {health.runbooks} runbooks
    </div>
  );
}

export default function App() {
  const [role, setRole] = useState<Role>(loadRole);
  const [tab, setTab] = useState<Tab>("queue");
  const [activeRun, setActiveRun] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(ROLE_KEY, role);
  }, [role]);

  function handleRunComplete(runId: string) {
    setActiveRun(runId);
    setTab("run");
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            OT
          </div>
          <div className="brand-text">
            <div className="brand-name">ops-triage-agent</div>
            <div className="brand-sub">operator console</div>
          </div>
        </div>

        <div className="topbar-right">
          <HealthPill role={role} />
          <label className="role-switch">
            <span className="role-label">Role</span>
            <select
              className="select"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              aria-label="Active role (selects the API key sent)"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <nav className="tabs" aria-label="Views">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab${tab === t.id ? " tab-active" : ""}`}
            aria-current={tab === t.id ? "page" : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === "queue" && (
          <Queue role={role} onRunComplete={handleRunComplete} />
        )}
        {tab === "run" && <RunDetail role={role} runId={activeRun} />}
        {tab === "approvals" && <Approvals role={role} />}
        {tab === "audit" && <Audit role={role} />}
        {tab === "evals" && <Evals role={role} />}
      </main>

      <footer className="footer">
        Enterprise agentic IT/Ops triage · RBAC, human approval gates,
        tamper-evident audit, and evals.
      </footer>
    </div>
  );
}
