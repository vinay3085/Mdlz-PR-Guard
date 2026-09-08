import hashlib
import hmac

from fastapi import HTTPException, Request


async def verify_webhook_signature(request: Request, webhook_secret: str) -> bytes:
    """
    Verifies the GitHub webhook HMAC-SHA256 signature.

    Uses hmac.compare_digest for timing-safe comparison to prevent
    timing-oracle attacks. Raises HTTP 401 on any verification failure.

    Returns the raw request body bytes for further processing.
    """
    body: bytes = await request.body()

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed X-Hub-Signature-256 header",
        )

    received_sig = signature_header[len("sha256="):]
    expected_sig = hmac.new(
        webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(received_sig, expected_sig):
        raise HTTPException(
            status_code=401,
            detail="Webhook signature verification failed",
        )

    return body
