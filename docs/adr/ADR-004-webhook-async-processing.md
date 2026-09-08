# ADR-004: Webhook Async Processing Pattern

**Status:** Accepted  
**Date:** 2026-08-17  
**Deciders:** Platform Engineering PoC team

---

## Context

GitHub expects webhook endpoints to respond within **10 seconds**. Our PR review pipeline (diff fetch → static analysis → LLM call) easily takes 15–60 seconds. We must decouple the HTTP response from the processing work.

## Decision

Use **FastAPI BackgroundTasks** to run the review pipeline asynchronously after immediately returning `{"status": "accepted"}` (HTTP 200) to GitHub.

```
GitHub POST /webhook
    │
    ├─► verify HMAC signature (sync, <1ms)
    ├─► parse event type (sync, <1ms)
    ├─► enqueue BackgroundTask(handler.handle_pull_request, payload)
    └─► return HTTP 200 {"status": "accepted"}   ← within 1s

[Background]
    ├─► fetch PR diff
    ├─► run static analysis (semgrep + gitleaks)
    ├─► run policy checks
    ├─► call LLM (claude-opus-5)
    ├─► persist findings + usage
    └─► post PR review + check run to GitHub
```

## Consequences

- **Positive:** GitHub always receives a timely response; no webhook delivery failures due to processing time
- **Positive:** Errors in the background task are isolated — they do not surface as 5xx to GitHub
- **Positive:** Simple to implement; no message queue infrastructure required for PoC
- **Negative:** If the process crashes mid-review, the review is lost (no retry). For production, replace BackgroundTasks with a queue (Celery + Redis, or AWS SQS)
- **Negative:** BackgroundTasks run in the same process; CPU-heavy static analysis blocks the event loop. Mitigated by running semgrep/gitleaks in subprocesses (already async-compatible via `asyncio.to_thread` if needed)

## Idempotency

The handler checks for an existing completed review of the same `(repo_full_name, head_sha)` pair before starting work. Duplicate webhook deliveries (GitHub retries) are safely skipped.

## Future Production Path

Replace `BackgroundTasks` with:
1. A persistent queue (Celery + Redis, or AWS SQS)
2. A separate worker process consuming from the queue
3. Retry logic with exponential back-off

The `WebhookHandler` class is queue-agnostic — it accepts a plain `dict` payload and can be called from any queue consumer without changes.
