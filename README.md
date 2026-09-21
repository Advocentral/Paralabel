# Paralabel — Gmail inbox triage for law firms

Paralabel watches a law firm's Gmail inbox and, as each email arrives, sorts it into
clear lanes — court deadlines, clients, opposing counsel, vendors, possible phishing,
and so on — by applying **Gmail labels**. Because it only writes labels, the results
show up in every Gmail client (web, phone, desktop) with nothing installed on anyone's
computer. Think of it as a paralegal that labels your inbox.

It is built for firms that care about client confidentiality: Paralabel sends its
classifier only the sender, subject, and a trimmed snippet of each email, **never
stores email bodies**, and never sends, forwards, or deletes mail. See
[docs/data-flow.md](docs/data-flow.md).

> **Status:** v0.1, under active development. The rules engine, classifiers, Gmail
> connect (poll + push), and evaluation harness are built. Dashboard and deployment
> polish follow.

## How it decides

1. When mail arrives, Paralabel asks a **classifier** a few fixed-choice questions
   (who sent this? is there a deadline? does it look like phishing?).
2. A firm-editable set of **rules** turns those answers into one or more Gmail labels
   under a `Paralabel/` parent.
3. Every email gets at least one label — an always-present fallback guarantees it.

The classifier is swappable (`CLASSIFIER=demo|jev|llm`):

- **demo** — deterministic keyword scoring, no API key needed. The whole app runs on it.
- **jev** — [TypeSafe](https://typesafe.ai) Jev, a small typed-judgment model (adapter; bring your own key).
- **llm** — any LLM behind a strict JSON schema (provider/model from config).

## Quick start (developers)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                              # unit + rules-engine tests
python -m evals.run --classifier demo   # report over 64 fictional law-firm emails
```

Full stack (Postgres + API):

```bash
cp .env.example .env      # then fill in secrets
docker compose up
```

## Rule sets and templates

Each firm starts from a **template** (general practice, bankruptcy, personal injury,
family law) and can then rename/recolor labels, add its own classifier questions, and
edit/reorder rules. Templates are plain JSON in
[`server/triage/templates/`](server/triage/templates/) and double as the import/export
format, so the community can contribute more.

## Repository layout

```
server/    FastAPI backend: app (api/config/db/models), mail (Gmail + push), triage (engine + classifiers), jobs
evals/     evaluation harness and fictional fixtures
docs/      setup, security, and data-flow documentation
```

## License

Apache-2.0. See [LICENSE](LICENSE).
