---
id: kb-password-reset
title: Password reset and account lockout
owner: identity-team
last_reviewed: 2026-05-01
tags: [password, lockout, mfa, access]
---

# Password reset and account lockout

When a user is locked out after repeated failed sign-ins, the account is
auto-locked for 30 minutes. To restore access sooner:

1. Verify the requester's identity against the user directory (name + manager).
2. Trigger a password reset for the account. This sends a one-time reset link to
   the user's registered email and clears the lockout counter.
3. If the user also reports MFA problems, see the MFA runbook — a password reset
   does not reset enrolled MFA devices.

A password reset is a **medium-risk** action: it must be requested by an operator
and approved by an admin before it executes, because it can be abused for account
takeover. Always confirm identity first.
