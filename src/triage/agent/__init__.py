"""The agent: planner + tool registry + run orchestration.

A triage run is a multi-step, tool-routing workflow:

    retrieve -> plan (LLM) -> gather context (DB tools) -> respond (LLM) -> act

Guarded actions in the final step are mediated by the enterprise-controls layer
(auth, approval gates, idempotency, retries, audit). The whole run emits a trace.
"""

from .runner import TriageResult, TriageRunner

__all__ = ["TriageResult", "TriageRunner"]
