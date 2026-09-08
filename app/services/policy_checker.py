import re
from typing import List

from app.services.interfaces import IPolicyChecker, PolicyViolation

# Ticket reference patterns (JIRA-style or GitHub issue references)
_TICKET_PATTERNS = [
    re.compile(r"[A-Z]+-\d+"),            # MDLZ-123, JIRA-456
    re.compile(r"#\d+", re.IGNORECASE),   # #123
    re.compile(r"fixes?\s+#\d+", re.IGNORECASE),
    re.compile(r"closes?\s+#\d+", re.IGNORECASE),
    re.compile(r"resolves?\s+#\d+", re.IGNORECASE),
]

_MIN_DESCRIPTION_LENGTH = 50
_MIN_TITLE_LENGTH = 10
_MAX_PR_LINES = 1000


class OrgPolicyChecker(IPolicyChecker):
    """
    Enforces Mondelēz Engineering org-level PR policies.

    Each policy is in its own method (SRP) so rules can be unit-tested and
    enabled/disabled independently without touching shared logic.
    """

    def check(self, pr_data: dict) -> List[PolicyViolation]:
        violations: List[PolicyViolation] = []
        violations.extend(self._check_ticket_reference(pr_data))
        violations.extend(self._check_description_length(pr_data))
        violations.extend(self._check_title_length(pr_data))
        violations.extend(self._check_pr_size(pr_data))
        violations.extend(self._check_draft_pr(pr_data))
        return violations

    # ── Individual rule methods ───────────────────────────────────────────────

    def _check_ticket_reference(self, pr_data: dict) -> List[PolicyViolation]:
        body = pr_data.get("body", "") or ""
        title = pr_data.get("title", "") or ""
        combined = f"{title} {body}"

        for pattern in _TICKET_PATTERNS:
            if pattern.search(combined):
                return []

        return [
            PolicyViolation(
                rule_id="POLICY-001",
                severity="medium",
                message=(
                    "PR title or description must reference a ticket "
                    "(e.g. MDLZ-123, PROJ-456, or #issue-number)."
                ),
            )
        ]

    def _check_description_length(self, pr_data: dict) -> List[PolicyViolation]:
        body = (pr_data.get("body", "") or "").strip()
        if len(body) < _MIN_DESCRIPTION_LENGTH:
            return [
                PolicyViolation(
                    rule_id="POLICY-002",
                    severity="low",
                    message=(
                        f"PR description is too short ({len(body)} chars). "
                        f"Please provide a meaningful description of at least {_MIN_DESCRIPTION_LENGTH} characters."
                    ),
                )
            ]
        return []

    def _check_title_length(self, pr_data: dict) -> List[PolicyViolation]:
        title = (pr_data.get("title", "") or "").strip()
        if len(title) < _MIN_TITLE_LENGTH:
            return [
                PolicyViolation(
                    rule_id="POLICY-003",
                    severity="low",
                    message=(
                        f"PR title is too short ({len(title)} chars). "
                        f"Please use a descriptive title of at least {_MIN_TITLE_LENGTH} characters."
                    ),
                )
            ]
        return []

    def _check_pr_size(self, pr_data: dict) -> List[PolicyViolation]:
        additions = pr_data.get("additions", 0) or 0
        deletions = pr_data.get("deletions", 0) or 0
        total = additions + deletions
        if total > _MAX_PR_LINES:
            return [
                PolicyViolation(
                    rule_id="POLICY-004",
                    severity="medium",
                    message=(
                        f"PR changes {total} lines (+{additions} / -{deletions}). "
                        f"PRs over {_MAX_PR_LINES} lines are hard to review — consider splitting into smaller PRs."
                    ),
                )
            ]
        return []

    def _check_draft_pr(self, pr_data: dict) -> List[PolicyViolation]:
        if pr_data.get("draft", False):
            return [
                PolicyViolation(
                    rule_id="POLICY-005",
                    severity="info",
                    message="This PR is in draft state. Security scan was performed but merge is not expected yet.",
                )
            ]
        return []
