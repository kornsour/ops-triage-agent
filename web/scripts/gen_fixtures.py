"""Generate the static-demo fixtures by driving the real FastAPI app.

Runs the whole system in-process against a throwaway temp DB/index, exercises the
endpoints exactly as the React app does, and dumps the responses to
web/src/demo/fixtures.json. The demo build (VITE_DEMO=1) serves these instead of
a live backend, so GitHub Pages hosts a fully clickable console with no server.

    uv run python web/scripts/gen_fixtures.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Isolated state so this never touches the real data dir.
_tmp = Path(tempfile.mkdtemp(prefix="ots-demo-"))
os.environ["TRIAGE_DB_PATH"] = str(_tmp / "triage.db")
os.environ["TRIAGE_INDEX_DIR"] = str(_tmp / "index")
os.environ["TRIAGE_AUDIT_PATH"] = str(_tmp / "audit.jsonl")
os.environ["TRIAGE_LLM_PROVIDER"] = "mock"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from fastapi.testclient import TestClient  # noqa: E402

from triage.config import get_settings  # noqa: E402

get_settings.cache_clear()

from triage.api.server import create_app  # noqa: E402

OPERATOR = {"X-API-Key": "demo-operator-key"}
ADMIN = {"X-API-Key": "demo-admin-key"}
VIEWER = {"X-API-Key": "demo-viewer-key"}


def main() -> None:
    app = create_app()
    client = TestClient(app)

    tickets = client.get("/tickets", headers=VIEWER).json()

    # Triage every ticket so we have a run + trace for each (and populate approvals/audit).
    runs_by_ticket: dict[str, str] = {}
    for t in tickets:
        r = client.post(f"/triage/{t['id']}", headers=OPERATOR).json()
        runs_by_ticket[t["id"]] = r["run_id"]

    runs = client.get("/runs", headers=VIEWER).json()
    run_detail = {
        run["run_id"]: client.get(f"/runs/{run['run_id']}", headers=VIEWER).json()
        for run in runs
    }

    # Build the eval report directly from the harness (same dict the endpoint returns).
    import run_evals  # noqa: E402

    evals = run_evals.run()

    fixtures = {
        "health": client.get("/health").json(),
        "tools": client.get("/tools").json(),
        "tickets": tickets,
        "runsByTicket": runs_by_ticket,
        "runs": runs,
        "runDetail": run_detail,
        "approvals": client.get("/approvals?status=pending", headers=VIEWER).json(),
        "audit": client.get("/audit", headers=VIEWER).json(),
        "auditVerify": client.get("/audit/verify", headers=VIEWER).json(),
        "evals": evals,
    }

    out = ROOT / "web" / "src" / "demo" / "fixtures.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixtures, indent=2))
    print(f"wrote {out} ({len(tickets)} tickets, {len(runs)} runs, "
          f"{len(fixtures['approvals'])} pending approvals, "
          f"{len(fixtures['audit'])} audit entries)")


if __name__ == "__main__":
    main()
