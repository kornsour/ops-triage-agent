---
id: kb-incident-response
title: Service outage and incident response
owner: sre-team
last_reviewed: 2026-06-10
tags: [outage, incident, 503, production, escalation]
---

# Service outage and incident response

When multiple users report the same service is unavailable (5xx errors, "everyone
is affected", a production service down), treat it as a potential incident — do
not handle it as a routine single-user ticket.

1. Classify severity as **high** immediately.
2. Escalate to the on-call SRE via the incident channel. Do not attempt
   remediation actions on production systems from the triage tool.
3. Link any duplicate tickets to the incident so reporters get a single update.

Escalation is a **low-risk** action (it notifies a human, it does not change
systems) and may auto-execute, but it is still recorded in the audit trail.
