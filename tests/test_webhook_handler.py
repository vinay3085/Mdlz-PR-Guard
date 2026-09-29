from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.handlers.webhook_handler import WebhookHandler
from app.services.interfaces import FeatureSet, LLMReviewResult, StaticFinding, PolicyViolation


def _make_handler(
    llm_risk="warn",
    llm_findings=None,
    static_findings=None,
    policy_violations=None,
):
    """Build a WebhookHandler with all dependencies mocked."""
    github_service = AsyncMock()
    github_service.get_pr_diff.return_value = "diff --git a/foo.py b/foo.py\n+print('hello')"
    github_service.post_review.return_value = None
    github_service.create_check_run.return_value = None

    analyzer = MagicMock()
    analyzer.analyze.return_value = static_findings or []

    policy = MagicMock()
    policy.check.return_value = policy_violations or []

    llm = AsyncMock()
    llm.review.return_value = LLMReviewResult(
        summary="No critical issues found.",
        overall_risk=llm_risk,
        findings=llm_findings or [],
        input_tokens=1000,
        output_tokens=500,
        cached_tokens=0,
        model="claude-opus-5",
    )

    composer = MagicMock()
    composer.compose.return_value = ("Review body", "Check summary")
    composer.get_review_event.return_value = "COMMENT"
    composer.get_check_conclusion.return_value = "neutral"

    pr_review_repo = MagicMock()
    mock_review = MagicMock()
    mock_review.id = 1
    mock_review.status = "pending"
    pr_review_repo.get_by_sha.return_value = None
    pr_review_repo.create_pending.return_value = mock_review
    pr_review_repo.mark_in_progress.return_value = mock_review
    pr_review_repo.mark_completed.return_value = mock_review

    findings_repo = MagicMock()
    ledger_repo = MagicMock()
    installation_repo = MagicMock()

    return WebhookHandler(
        github_service=github_service,
        static_analyzer=analyzer,
        policy_checker=policy,
        llm_reviewer=llm,
        comment_composer=composer,
        pr_review_repo=pr_review_repo,
        findings_repo=findings_repo,
        usage_ledger_repo=ledger_repo,
        installation_repo=installation_repo,
        features=FeatureSet(
            static_analysis=True,
            secret_scanning=True,
            policy_check=True,
            llm_findings=True,
        ),
    )


SAMPLE_PR_PAYLOAD = {
    "action": "opened",
    "number": 42,
    "pull_request": {
        "number": 42,
        "head": {"sha": "abc123def456" * 3 + "abcd"},
        "title": "MDLZ-123 add login feature",
        "body": "This adds OAuth2 login. " * 5,
        "additions": 100,
        "deletions": 20,
        "draft": False,
    },
    "repository": {"full_name": "myorg/myrepo"},
    "installation": {"id": 999},
}


@pytest.mark.asyncio
async def test_handle_pull_request_runs_full_pipeline():
    handler = _make_handler()
    await handler.handle_pull_request(SAMPLE_PR_PAYLOAD)

    handler._github.get_pr_diff.assert_awaited_once()
    handler._analyzer.analyze.assert_called_once()
    handler._policy.check.assert_called_once()
    handler._llm.review.assert_awaited_once()
    handler._github.post_review.assert_awaited_once()
    handler._github.create_check_run.assert_awaited_once()
    handler._pr_reviews.mark_completed.assert_called_once()


@pytest.mark.asyncio
async def test_handle_pull_request_ignores_non_relevant_actions():
    handler = _make_handler()
    payload = {**SAMPLE_PR_PAYLOAD, "action": "labeled"}
    await handler.handle_pull_request(payload)
    handler._github.get_pr_diff.assert_not_called()


@pytest.mark.asyncio
async def test_handle_pull_request_skips_duplicate_sha():
    handler = _make_handler()
    existing = MagicMock()
    existing.status = "completed"
    handler._pr_reviews.get_by_sha.return_value = existing

    await handler.handle_pull_request(SAMPLE_PR_PAYLOAD)
    handler._github.get_pr_diff.assert_not_called()


@pytest.mark.asyncio
async def test_handle_installation_upsert():
    handler = _make_handler()
    payload = {
        "action": "created",
        "installation": {"id": 777, "account": {"login": "myorg"}},
    }
    await handler.handle_installation(payload)
    handler._installations.upsert.assert_called_once_with(
        installation_id=777, org="myorg", account_login="myorg", status="active"
    )


@pytest.mark.asyncio
async def test_handle_pull_request_passes_pr_metadata_to_llm():
    handler = _make_handler()

    await handler.handle_pull_request(SAMPLE_PR_PAYLOAD)

    kwargs = handler._llm.review.await_args.kwargs
    assert kwargs["pr_title"] == "MDLZ-123 add login feature"
    assert kwargs["pr_body"] == "This adds OAuth2 login. " * 5


@pytest.mark.asyncio
async def test_handle_pull_request_marks_failed_on_error():
    handler = _make_handler()
    handler._github.get_pr_diff.side_effect = RuntimeError("network error")

    with pytest.raises(RuntimeError):
        await handler.handle_pull_request(SAMPLE_PR_PAYLOAD)

    handler._pr_reviews.mark_failed.assert_called_once()
