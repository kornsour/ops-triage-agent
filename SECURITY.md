# Security policy

## Reporting a vulnerability

Please report vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/kornsour/ops-triage-agent/security/advisories/new).
Do not open a public issue for a suspected vulnerability. Include the affected
commit, reproduction steps, impact, and any suggested mitigation.

Only the current default branch is supported until the project publishes a
stable release series.

## Demonstration boundary

The public Pages site is an in-browser demonstration with mock data and no
backend. It must not be treated as an authenticated production deployment.

The backend's API-key roles, approval gates, sandbox interface, tamper-evident
audit records, and prompt-injection handling are reference controls. A real
deployment must additionally provide managed identity and secret distribution,
TLS, durable shared storage appropriate for its replica model, centralized
audit export and retention, network policy, and an organization-specific
authorization policy.

Never use real tickets, credentials, personal data, or production system access
in the public demo or test fixtures.
