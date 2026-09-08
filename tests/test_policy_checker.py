import pytest
from app.services.policy_checker import OrgPolicyChecker


@pytest.fixture
def checker():
    return OrgPolicyChecker()


def _pr(title="", body="", additions=10, deletions=5, draft=False):
    return {
        "title": title,
        "body": body,
        "additions": additions,
        "deletions": deletions,
        "draft": draft,
    }


def test_ticket_reference_jira_style(checker):
    violations = checker.check(_pr(title="MDLZ-123: add feature", body="Some description " * 5))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-001" not in rule_ids


def test_ticket_reference_github_issue(checker):
    violations = checker.check(_pr(title="Fix bug", body="Closes #456. " + "Details. " * 5))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-001" not in rule_ids


def test_ticket_reference_missing(checker):
    violations = checker.check(_pr(title="Add feature", body="Some details. " * 5))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-001" in rule_ids


def test_description_too_short(checker):
    violations = checker.check(_pr(title="MDLZ-1 fix", body="Short"))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-002" in rule_ids


def test_description_adequate(checker):
    violations = checker.check(_pr(title="MDLZ-1 fix", body="A" * 60))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-002" not in rule_ids


def test_title_too_short(checker):
    violations = checker.check(_pr(title="Fix", body="A" * 60))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-003" in rule_ids


def test_pr_too_large(checker):
    violations = checker.check(_pr(title="MDLZ-1 big refactor", body="A" * 60, additions=800, deletions=400))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-004" in rule_ids


def test_pr_size_ok(checker):
    violations = checker.check(_pr(title="MDLZ-1 small fix", body="A" * 60, additions=50, deletions=20))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-004" not in rule_ids


def test_draft_pr_gets_info(checker):
    violations = checker.check(_pr(title="MDLZ-1 WIP", body="A" * 60, draft=True))
    rule_ids = [v.rule_id for v in violations]
    assert "POLICY-005" in rule_ids


def test_clean_pr_no_violations(checker):
    violations = checker.check(
        _pr(title="MDLZ-123 add feature", body="This PR adds a new authentication module. " * 3, additions=50, deletions=10)
    )
    assert violations == []
