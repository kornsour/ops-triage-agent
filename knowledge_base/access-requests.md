---
id: kb-access-requests
title: Access and permission requests
owner: identity-team
last_reviewed: 2026-04-18
tags: [access, permission, repo, group, provisioning]
---

# Access and permission requests

Requests to grant repository access, security-group membership, or elevated roles
follow least-privilege provisioning.

1. Confirm the requester's department and manager from the directory.
2. Check that the access requested matches the user's role. Cross-department
   access (e.g. Finance requesting an Engineering repo) requires explicit manager
   sign-off captured in the approval reason.
3. Grant the narrowest scope that satisfies the request. Prefer group membership
   over per-user grants.

Granting access is a **high-risk** action. It always requires admin approval and a
recorded justification, and every grant is written to the audit trail with the
approving admin's identity.
