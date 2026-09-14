# Contributing

Open a focused pull request against `main` and describe the behavior changed,
the security implications, and the verification performed.

Before submitting:

```bash
make install
make lint
make test
make eval-gate
cd web
npm ci
npm run build
npm run build:demo
```

New guarded actions must declare a risk policy and pass through the shared
approval, idempotency, sandbox, and audit path. New benchmarks belong in the
evaluation registry and must define explicit gates. Never commit credentials,
real support tickets, personal data, generated databases, or evaluation
reports.
