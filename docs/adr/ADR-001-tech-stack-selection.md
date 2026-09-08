# ADR-001: Tech Stack Selection

**Status:** Accepted  
**Date:** 2026-08-17  
**Deciders:** Platform Engineering PoC team

---

## Context

We need to build a GitHub App-based PR security scanner as a proof-of-concept. The solution must be:
- Fast to develop and iterate on
- Runnable locally for demos without cloud infrastructure
- Extensible to production once validated

## Decision

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Strong security tooling ecosystem; Semgrep, Gitleaks, Anthropic SDK all have first-class Python support |
| Web framework | FastAPI | Async-native, automatic OpenAPI docs, excellent Pydantic integration, minimal boilerplate |
| ASGI server | Uvicorn | Production-grade, standard pair for FastAPI |
| GitHub integration | Raw HTTP via httpx + PyJWT | Fine-grained control over API calls; PyGithub does not expose all GitHub API endpoints (check-runs, PR reviews) |
| Static analysis | Semgrep CLI + Gitleaks CLI | Industry standard tools; subprocess wrapper is clean and avoids SDK version conflicts |
| LLM | Anthropic Claude (claude-opus-5) | See ADR-002 |
| Storage | SQLite via SQLAlchemy ORM | See ADR-003 |
| Local tunnel | ngrok | Industry standard for local webhook testing; one-command setup |
| Config management | pydantic-settings | Type-safe, env-var-first, integrates seamlessly with FastAPI DI |

## Consequences

- **Positive:** Low setup friction; single-process app; no Docker required for PoC
- **Positive:** Python ecosystem gives rich tooling for security scanning
- **Negative:** SQLite is not production-grade for concurrent writes; swap to PostgreSQL when scaling (see ADR-003)
- **Negative:** Semgrep/Gitleaks must be installed separately on the host

## Alternatives Considered

- **Node.js + Express:** Rejected — Python has better security tooling ecosystem
- **Go:** Rejected — Development velocity lower for PoC; team more familiar with Python
- **Django:** Rejected — Too heavy for a focused microservice; FastAPI is a better fit
