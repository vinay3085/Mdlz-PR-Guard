import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app

SECRET = "super-secret-webhook-key-12345"


def _make_signature(body: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.fixture
def client(monkeypatch):
    """Patch settings so the app boots without a real .env."""
    from app import config

    class _FakeSettings:
        github_app_id = 123456
        github_private_key_path = "./certs/private_key.pem"
        github_webhook_secret = SECRET
        llm_provider = "anthropic"
        anthropic_api_key = "sk-test"
        llm_model = "claude-opus-5"
        app_host = "0.0.0.0"
        app_port = 8000
        log_level = "INFO"
        database_url = "sqlite://"  # in-memory for tests
        prompts_dir = "./prompts"

    monkeypatch.setattr(config, "get_settings", lambda: _FakeSettings())
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_webhook_rejects_missing_signature(client):
    payload = json.dumps({"action": "opened"}).encode()
    resp = client.post("/webhook", content=payload, headers={"X-GitHub-Event": "pull_request"})
    assert resp.status_code == 401


def test_webhook_rejects_wrong_signature(client):
    payload = json.dumps({"action": "opened"}).encode()
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )
    assert resp.status_code == 401


def test_webhook_accepts_valid_signature(client):
    payload = json.dumps({"action": "labeled"}).encode()
    sig = _make_signature(payload, SECRET)
    resp = client.post(
        "/webhook",
        content=payload,
        headers={
            "X-GitHub-Event": "issues",  # unknown event — should still return 200
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}
