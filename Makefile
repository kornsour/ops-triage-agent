# ops-triage-agent — common workflows. Uses `uv` for a reproducible env.
.DEFAULT_GOAL := help
PY := uv run

.PHONY: help install seed demo serve web test eval eval-gate drift lint fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv (pinned Python 3.14) and install dev deps
	uv venv --python 3.14
	uv pip install -e ".[dev]"

seed: ## Build the SQLite ticket DB + RAG index from seed data
	$(PY) -m triage.data.seed
	$(PY) -m triage.rag.ingest

demo: seed ## Run an end-to-end triage on a seeded ticket and print the trace
	$(PY) -m triage.cli demo

serve: ## Start the FastAPI backend on :8000
	$(PY) -m uvicorn triage.api.server:app --reload --port 8000

web: ## Start the TypeScript front-end dev server (proxies to :8000)
	cd web && npm install && npm run dev

test: ## Run the pytest suite (fully offline)
	$(PY) -m pytest

eval: seed ## Run the eval harness against the golden set and write a report
	$(PY) evals/run_evals.py

eval-gate: ## Run evals and FAIL if any quality gate regresses (used in CI)
	$(PY) evals/run_evals.py --gate

drift: ## Compare the two most recent eval reports for metric drift
	$(PY) evals/drift.py

lint: ## Lint with ruff
	$(PY) -m ruff check src evals tests mcp_server

fmt: ## Auto-format with ruff
	$(PY) -m ruff check --fix src evals tests mcp_server

clean: ## Remove generated state (db, index, reports, caches)
	rm -rf .triage *.db data/index evals/reports/*.json .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
