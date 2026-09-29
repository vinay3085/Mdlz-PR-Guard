import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.services.github_auth import GitHubAuthService

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
        github_private_key_content = "-----BEGIN PRIVATE KEY-----\nplaceholder\n-----END PRIVATE KEY-----"
        github_webhook_secret = SECRET
        llm_provider = "anthropic"
        anthropic_api_key = "sk-test"
        openai_api_key = ""
        llm_model = "claude-opus-5"
        databricks_host = ""
        databricks_token = ""
        app_host = "0.0.0.0"
        app_port = 8000
        log_level = "INFO"
        database_url = "sqlite://"  # in-memory for tests
        prompts_dir = "./prompts"
        feature_databricks_fetch = False
        databricks_workspace_path = "/"
        feature_static_analysis = False
        feature_secret_scanning = False
        feature_policy_check = False
        feature_llm_findings = False
        langsmith_tracing = False
        langsmith_api_key = ""
        langsmith_project = "mdlz-pr-guard"

    fake_settings = lambda: _FakeSettings()
    fake_settings.cache_clear = lambda: None
    async def _fake_validate_credentials(self):
        return None
    monkeypatch.setattr(config, "get_settings", fake_settings)
    monkeypatch.setattr(main_module, "get_settings", fake_settings)
    monkeypatch.setattr(GitHubAuthService, "validate_credentials", _fake_validate_credentials)
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
