# Deploying the Paralabel API (Railway)

## What the deployed service contains

One container running the Paralabel FastAPI app (`server.app.main:app`, built from
`server/Dockerfile`). It serves:

- `GET /health` — health check (Railway pings this).
- `GET /api/info` — classifier + mode + templates.
- `POST /api/demo/triage` — the public "try the triage" endpoint the marketing site
  calls. Runs the real rules engine + classifier, returns scores + labels, **stores
  nothing**, and is rate-limited with a daily Jev budget cap.
- `GET/POST /api/google/*` and `/api/google/push` — the OAuth connect + Gmail
  poll/push routes. Present but idle until a firm connects an inbox.

It also contains the rules engine, guardrails, the four templates, and the classifiers
(`demo` now; `jev`/`llm` when configured). No email bodies are ever stored.

**For the demo endpoint you do NOT need Postgres or Google credentials** — that route is
stateless. Add Postgres + Gmail creds later, only when you run real inboxes.

## Deploy — option A: connect the GitHub repo (recommended)

1. Railway → **New Project → Deploy from GitHub repo** → `Advocentral/Paralabel`.
2. Railway reads `railway.json` and builds with `server/Dockerfile`.
3. Add the environment variables below (Variables tab).
4. Deploy. Every push to `master` redeploys automatically.

## Deploy — option B: Railway CLI

```bash
railway login          # opens a browser
railway init           # create/select a project
railway up             # builds with server/Dockerfile and deploys
railway variables set CLASSIFIER=demo DEMO_SHARED_SECRET=... # etc.
```

## Environment variables

**Demo-only (minimum to power the site's /try page):**

| Var | Value |
|---|---|
| `CLASSIFIER` | `demo` (switch to `jev` once the key is set) |
| `DEMO_SHARED_SECRET` | a random string; the website sends it as `X-Demo-Token` |
| `DEMO_RATE_PER_HOUR` | e.g. `20` |
| `DEMO_DAILY_JEV_BUDGET` | e.g. `1000` |
| `TURNSTILE_SECRET` | optional — Cloudflare Turnstile secret |

**Real Jev (Milestone 7):**

| Var | Value |
|---|---|
| `CLASSIFIER` | `jev` |
| `JEV_API_KEY` | your TypeSafe key |
| `JEV_BASE_URL` | TypeSafe base URL (per their docs) |

**Full inbox triage (later — needs a Railway Postgres plugin):**

`DATABASE_URL`, `TOKEN_ENCRYPTION_KEY` (Fernet), `APP_SECRET`,
`GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`, `GMAIL_MODE` (`push`),
`PUBSUB_TOPIC/AUDIENCE/SERVICE_ACCOUNT`, `SMTP_*`. Then run `alembic upgrade head`.

## Verify

```bash
curl https://<your-app>.up.railway.app/health          # {"status":"ok"}
curl -X POST https://<your-app>.up.railway.app/api/demo/triage \
  -H 'content-type: application/json' -H 'x-demo-token: <DEMO_SHARED_SECRET>' \
  -d '{"sender_email":"ecf@txsd.uscourts.gov","subject":"Notice of Electronic Filing","body":"The Clerk docketed. CM/ECF. Response due tomorrow."}'
# -> labels include "Deadlines & court"
```

## Wire the website

On the Advocentral site (also Railway), set:

```
PARALABEL_DEMO_URL=https://<your-app>.up.railway.app/api/demo/triage
PARALABEL_DEMO_TOKEN=<same as DEMO_SHARED_SECRET>
```

Then `/try` posts through its same-origin proxy → this API → back with the scores.
