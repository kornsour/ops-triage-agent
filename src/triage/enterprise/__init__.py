"""Enterprise controls: the layer most public agent demos skip.

    auth         API-key -> role resolution and permission checks.
    approvals    Human-in-the-loop approval gates for guarded actions.
    audit        Append-only, hash-chained audit trail.
    idempotency  Dedupe identical action requests (idempotency keys).
    ratelimit    Token-bucket rate limiting per principal.
    retry        Bounded retry with exponential backoff for flaky tools.
"""

from .approvals import ApprovalRequired, ApprovalStore, Decision
from .audit import AuditLog
from .auth import AuthError, Principal, authenticate, require_role
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore
from .ratelimit import RateLimitExceeded, TokenBucket
from .retry import retry

__all__ = [
    "ApprovalRequired",
    "ApprovalStore",
    "Decision",
    "AuditLog",
    "AuthError",
    "Principal",
    "authenticate",
    "require_role",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RateLimitExceeded",
    "TokenBucket",
    "retry",
]
