"""API-key authentication and role-based permission checks.

Roles form a strict hierarchy: viewer < operator < admin.
    viewer    read tickets, runs, audit
    operator  request guarded actions (which then need approval)
    admin     approve/deny guarded actions
"""

from __future__ import annotations

from dataclasses import dataclass

from triage.config import Settings, get_settings

_ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


class AuthError(Exception):
    """Raised on a missing/invalid key or insufficient role."""


@dataclass(frozen=True)
class Principal:
    api_key: str
    role: str

    @property
    def name(self) -> str:
        return f"{self.role}:{self.api_key[:8]}"

    def has_role(self, minimum: str) -> bool:
        return _ROLE_RANK.get(self.role, -1) >= _ROLE_RANK[minimum]


def authenticate(api_key: str | None, settings: Settings | None = None) -> Principal:
    settings = settings or get_settings()
    if not api_key:
        raise AuthError("missing API key")
    role = settings.parsed_api_keys().get(api_key)
    if role is None:
        raise AuthError("invalid API key")
    return Principal(api_key=api_key, role=role)


def require_role(principal: Principal, minimum: str) -> None:
    if minimum not in _ROLE_RANK:
        raise ValueError(f"unknown role {minimum!r}")
    if not principal.has_role(minimum):
        raise AuthError(f"role {principal.role!r} lacks required role {minimum!r}")
