# Data flow — what leaves the server, and what we store

This document is a contract. It is kept in sync with the code; if the code and this
document disagree, that is a bug. The relevant code lives in
`server/triage/body.py`, `server/triage/classifier.py`, and `server/app/models.py`.

## What the classifier receives

For each incoming email, the triage worker sends the classifier **only**:

- the sender display name,
- the sender email address,
- the subject line,
- the first 500 characters of the **plain-text** body, after:
  - stripping HTML (`clean_body` in `body.py`),
  - removing quoted reply history (lines starting with `>`, `-----Original Message-----`, `On … wrote:`),
  - removing signatures (content after a `-- ` delimiter).

It never sends:

- attachments or their contents,
- other recipients (To/Cc/Bcc beyond the sender),
- thread history or earlier messages,
- calendar data, contacts, or anything outside the single message.

The shape is defined by `TriageInput` in `server/triage/classifier.py`, which has no
field for any of the excluded data — it is impossible to send them without changing
this document and the type.

## What we store

Per triaged email we persist (see `TriageRecord` in `server/app/models.py`):

- message ID, thread ID, received time,
- sender email, subject,
- applied labels, the matched rule key, and the rule-set version,
- the full per-question probabilities JSON,
- classifier name, latency, input tokens, and estimated cost.

We **do not** store email bodies. `TriageRecord` has no body column.

## Retention

- Triage records and corrections are purged after a configurable retention period
  (`RETENTION_DAYS`, default 30) by a daily job (Milestone 6).
- An append-only audit log records connections, rule changes, triage decisions, and
  manual reassignments.

## Write-back

- Default write-back is **label only**.
- Opt-in actions (mark important, star, archive, mark read) follow the guardrails in
  `server/triage/validate.py`: rules keyed off court senders, the deadline window, or
  phishing may not archive or mark read.
- The service never sends, forwards, or deletes email, never opens links, and never
  downloads attachments. There are no such actions in the code (`RuleActions` in
  `server/triage/rules.py` has no send/forward/delete fields).

## OAuth scope

The only Gmail scope requested is `https://www.googleapis.com/auth/gmail.modify`
(plus `openid` and `email` for sign-in). This covers reading message metadata and
creating/applying/editing labels. No send, no full-mailbox export scope.
