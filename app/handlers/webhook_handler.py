import logging
import time
from typing import List

from app.repositories.findings_repo import FindingsRepository
from app.repositories.installation_repo import InstallationRepository
from app.repositories.pr_review_repo import PRReviewRepository
from app.repositories.usage_ledger_repo import UsageLedgerRepository
from app.services.comment_composer import CommentComposer
from app.services.interfaces import (
    FeatureSet,
    IGitHubService,
    ILLMReviewer,
    IPolicyChecker,
    IStaticAnalyzer,
    PolicyViolation,
    StaticFinding,
)

logger = logging.getLogger(__name__)


class WebhookHandler:
    """
    Orchestrates the full PR review pipeline.

    Depends only on abstract interfaces (Dependency Inversion Principle),
    making each dependency independently replaceable and testable.
    Feature gates are controlled by the FeatureSet injected at construction time.
    """

    def __init__(
        self,
        github_service: IGitHubService,
        static_analyzer: IStaticAnalyzer,
        policy_checker: IPolicyChecker,
        llm_reviewer: ILLMReviewer,
        comment_composer: CommentComposer,
        pr_review_repo: PRReviewRepository,
        findings_repo: FindingsRepository,
        usage_ledger_repo: UsageLedgerRepository,
        installation_repo: InstallationRepository,
        features: FeatureSet,
    ) -> None:
        self._github = github_service
        self._analyzer = static_analyzer
        self._policy = policy_checker
        self._llm = llm_reviewer
        self._composer = comment_composer
        self._pr_reviews = pr_review_repo
        self._findings = findings_repo
        self._ledger = usage_ledger_repo
        self._installations = installation_repo
        self._features = features

    # ── Event handlers ────────────────────────────────────────────────────────

    async def handle_installation(self, payload: dict) -> None:
        action = payload.get("action", "")
        installation = payload.get("installation", {})
        installation_id = installation.get("id")
        account = installation.get("account", {})
        org = account.get("login", "")

        status_map = {
            "created": "active",
            "deleted": "deleted",
            "suspend": "suspended",
            "unsuspend": "active",
        }

        self._installations.upsert(
            installation_id=installation_id,
            org=org,
            account_login=org,
            status=status_map.get(action, "active"),
        )
        logger.info("Installation %d (%s): action=%s", installation_id, org, action)

    async def handle_pull_request(self, payload: dict) -> None:
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            logger.debug("Ignoring PR action: %s", action)
            return

        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        installation = payload.get("installation", {})

        installation_id: int = installation.get("id")
        repo_full_name: str = repo.get("full_name", "")
        pr_number: int = pr.get("number", 0)
        head_sha: str = pr.get("head", {}).get("sha", "")

        if not all([installation_id, repo_full_name, pr_number, head_sha]):
            logger.warning("Incomplete PR payload — skipping: %s", payload.get("number"))
            return

        # Idempotency check — skip if we already completed a review for this SHA
        existing = self._pr_reviews.get_by_sha(repo_full_name, head_sha)
        if existing and existing.status == "completed":
            logger.info(
                "Duplicate delivery for %s#%d sha=%s — skipping",
                repo_full_name, pr_number, head_sha[:8],
            )
            return

        pr_review = self._pr_reviews.create_pending(
            installation_id, repo_full_name, pr_number, head_sha
        )
        self._pr_reviews.mark_in_progress(pr_review)
        pipeline_start = time.monotonic()

        try:
            # ── Step 1: Fetch PR diff ─────────────────────────────────────
            logger.info("Fetching diff for %s#%d", repo_full_name, pr_number)
            diff = await self._github.get_pr_diff(installation_id, repo_full_name, pr_number)

            # ── Step 2: Static analysis (conditional) ────────────────────
            static_findings: List[StaticFinding] = []
            if self._features.any_static:
                static_findings = self._analyzer.analyze(diff)
                logger.info("Static analysis: %d finding(s)", len(static_findings))
            else:
                logger.info("Static analysis: skipped (FEATURE_STATIC_ANALYSIS=false, FEATURE_SECRET_SCANNING=false)")

            # ── Step 3: Policy checks (conditional) ──────────────────────
            policy_violations: List[PolicyViolation] = []
            if self._features.policy_check:
                policy_violations = self._policy.check(pr)
                logger.info("Policy check: %d violation(s)", len(policy_violations))
            else:
                logger.info("Policy check: skipped (FEATURE_POLICY_CHECK=false)")

            # ── Step 4: LLM review (always runs; adapts based on features) ─
            llm_start = time.monotonic()
            llm_result = await self._llm.review(
                diff,
                static_findings,
                policy_violations,
                self._features,
                pr_title=pr.get("title", "") or "",
                pr_body=pr.get("body", "") or "",
            )
            llm_latency_ms = int((time.monotonic() - llm_start) * 1000)
            logger.info(
                "LLM review: %d file(s) described, %d finding(s), risk=%s, latency=%dms",
                len(llm_result.file_changes),
                len(llm_result.findings),
                llm_result.overall_risk,
                llm_latency_ms,
            )

            # ── Step 5: Persist findings ──────────────────────────────────
            if static_findings:
                self._findings.bulk_insert_static(pr_review.id, static_findings)
            if policy_violations:
                self._findings.bulk_insert_policy(pr_review.id, policy_violations)
            if llm_result.findings:
                self._findings.bulk_insert_llm(pr_review.id, llm_result.findings)

            # ── Step 6: Record LLM usage ──────────────────────────────────
            self._ledger.record_llm_usage(pr_review.id, llm_result, llm_latency_ms)

            # ── Step 7: Compose and post PR review ───────────────────────
            review_body, check_summary = self._composer.compose(
                static_findings, policy_violations, llm_result, self._features
            )
            review_event = self._composer.get_review_event(llm_result, self._features)
            check_conclusion = self._composer.get_check_conclusion(llm_result, self._features)

            await self._github.post_review(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                commit_sha=head_sha,
                body=review_body,
                event=review_event,
            )

            # ── Step 8: Create Check Run ──────────────────────────────────
            await self._github.create_check_run(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                head_sha=head_sha,
                conclusion=check_conclusion,
                title=f"PR Guard — {llm_result.overall_risk.upper()}",
                summary=check_summary,
            )

            # ── Step 9: Mark review completed ────────────────────────────
            total_findings = (
                len(static_findings) + len(policy_violations) + len(llm_result.findings)
            )
            critical_count = sum(1 for f in static_findings if f.severity == "critical")
            high_count = sum(1 for f in static_findings if f.severity == "high")
            total_latency_ms = int((time.monotonic() - pipeline_start) * 1000)

            self._pr_reviews.mark_completed(
                pr_review, total_findings, critical_count, high_count, total_latency_ms
            )
            logger.info(
                "Review complete for %s#%d: %d finding(s), risk=%s, total_latency=%dms",
                repo_full_name, pr_number, total_findings,
                llm_result.overall_risk, total_latency_ms,
            )

        except Exception as exc:
            logger.exception(
                "Pipeline failed for %s#%d: %s", repo_full_name, pr_number, exc
            )
            self._pr_reviews.mark_failed(pr_review, str(exc))
            raise
        finally:
            self._pr_reviews.close()
