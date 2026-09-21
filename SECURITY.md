# Security

## Reporting a vulnerability

Please report suspected vulnerabilities privately to the maintainers (see repository
contact) rather than opening a public issue. We aim to acknowledge reports within a
few business days.

Paralabel is open-source (Apache-2.0). This page describes its security posture.

## Security posture (v0.1)

- **Minimal Gmail scope.** Only `gmail.modify` (plus `openid`, `email`) is requested.
  No send, no full-export scope.
- **No email bodies at rest.** Only metadata, labels, and probabilities are stored.
  See [docs/data-flow.md](docs/data-flow.md).
- **Encrypted refresh tokens.** Google refresh tokens are encrypted at rest with a
  Fernet key from `TOKEN_ENCRYPTION_KEY`. Tokens are never logged.
- **Label-only write-back by default.** Opt-in actions are constrained by backend
  guardrails; the service never sends, forwards, or deletes mail, opens links, or
  downloads attachments.
- **Secrets in environment only.** Only `.env.example` is committed; real secrets live
  in the environment.
- **Push verification.** The Pub/Sub push endpoint verifies the Google-signed JWT
  (audience + service account) before processing (Milestone 3).

## Hardening still to come

Later milestones add the authenticated dashboard (magic-link sign-in), the audit log,
the retention purge job, and the full deployment guide. This file is finalized at
Milestone 8.
