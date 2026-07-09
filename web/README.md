# ops-triage-agent — operator console

A Vite + React + TypeScript dashboard for the `ops-triage-agent` FastAPI
backend. It is the operator/admin console for the IT/Ops ticket-triage system:
run triage on a ticket, inspect the agent's tool-calling trace, work the human
approval gates (RBAC), verify the tamper-evident audit log, and review
eval/quality metrics.

## Prerequisites

- Node 24 + npm (any recent Node 18+ works)
- The backend running on **http://localhost:8000** — from the repo root run
  `make serve` (Vite proxies `/api/*` to it).

## Getting started

```bash
npm install     # install dependencies
npm run dev     # start the Vite dev server (http://localhost:5173)
```

Then open http://localhost:5173. The dev server proxies every `/api/*` request
to `http://localhost:8000`, so make sure the backend is up first.

Other scripts:

```bash
npm run build   # type-check (tsc -b) + production build into web/dist
npm run preview # serve the production build locally
```

## The role switcher (RBAC demo)

The top-right **Role** dropdown chooses which demo API key is sent on every
request via the `X-API-Key` header. This is how role-based access control is
demonstrated end-to-end:

| Role     | Demo key            | Can do                                  |
| -------- | ------------------- | --------------------------------------- |
| viewer   | `demo-viewer-key`   | read-only (tickets, runs, audit, evals) |
| operator | `demo-operator-key` | + run triage / request actions          |
| admin    | `demo-admin-key`    | + approve or deny gated actions         |

The selection is persisted in `localStorage` and defaults to **operator**.
When the backend rejects an action for the current role (401/403), the UI
surfaces a friendly "your current role can't do this" message instead of
crashing — switch roles and retry.

## Views

1. **Queue** — all tickets; run triage (operator/admin) to open the run detail.
2. **Run Detail** — status, classification, summary, a vertical trace timeline
   (guard → reason → respond → act), the draft reply, citation chips, a grounded
   indicator, and a metrics row. Flags runs awaiting admin approval, and surfaces
   a warning when a prompt-injection attempt was detected in the ticket. Runs are
   shareable via a `#run=<id>` deep link.
3. **Approvals** — pending approvals (auto-polled). Admins approve/deny with an
   optional reason; the execution result is shown afterward.
4. **Audit** — the hash-chained audit log with a prominent
   "Chain verified ✓ / BROKEN ✗" badge from `/audit/verify`.
5. **Evals** — metric cards and a per-scenario table from the latest eval
   report. If no report exists yet, run `make eval` from the repo root.

## Tech notes

- Minimal dependencies: React 18 + plain CSS only (no UI kit, Tailwind, Redux,
  or router). Tab navigation is simple component state.
- Strict TypeScript; the full API contract is typed in `src/types.ts`.
- The API client (`src/api.ts`) targets the `/api` base so the Vite proxy
  handles CORS/origin in development.
