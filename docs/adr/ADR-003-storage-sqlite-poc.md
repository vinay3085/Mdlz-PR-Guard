# ADR-003: Storage — SQLite for PoC

**Status:** Accepted  
**Date:** 2026-08-17  
**Deciders:** Platform Engineering PoC team

---

## Context

We need persistent storage for:
- GitHub App installation records
- Per-PR review records (status, latency, finding counts)
- Individual findings (source, severity, file, line, message)
- Org policy rules
- LLM usage ledger (tokens, cost)

For production this would be a managed relational database. For the PoC the priority is zero-infrastructure setup.

## Decision

Use **SQLite** (via SQLAlchemy ORM) for the PoC.

- Database file: `mdlz_pr_guard.db` in the project root (gitignored)
- All DB access goes through SQLAlchemy ORM — no raw SQL strings anywhere
- `DATABASE_URL` env var controls the connection string; swapping to PostgreSQL requires only changing this value and the SQLAlchemy driver package

## Schema (from DBML design)

| Table | Purpose |
|---|---|
| `installations` | GitHub App installation_id, org, status |
| `pr_reviews` | Per-SHA review record: status, latency, finding counts |
| `findings` | Unified finding store: source (static/llm/policy), severity, file, line, message, dedupe_hash |
| `policy_rules` | Versioned org-specific policy rule definitions |
| `usage_ledger` | Per-LLM-call metrics: model, tokens (input/output/cached), cost_usd |

## Migration Path to Production

1. Set `DATABASE_URL=postgresql+psycopg2://user:pass@host/db`
2. Install `psycopg2-binary`
3. Run `Base.metadata.create_all(engine)` or migrate via Alembic
4. No application code changes required

## Consequences

- **Positive:** Zero infrastructure; runs anywhere Python runs
- **Positive:** SQLAlchemy ORM abstracts the DB engine; migration is a one-line config change
- **Negative:** SQLite has limited concurrent write throughput — not suitable for multi-process deployment
- **Negative:** No built-in connection pooling; acceptable for single-process PoC
- **Risk:** `check_same_thread=False` is required for FastAPI's async-to-sync bridging; mitigated by single-process deployment

## Security Notes

- The SQLite file must be excluded from version control (`.gitignore`)
- No raw SQL strings; all queries use SQLAlchemy ORM to prevent SQL injection
