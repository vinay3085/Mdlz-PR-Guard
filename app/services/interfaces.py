"""
SOLID interfaces for the Mdlz PR Guard scanning pipeline.

Each interface has a single responsibility (SRP) and is consumed via
dependency inversion (DIP) — callers depend on these abstractions, not
on concrete implementations.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


# ── Value objects ────────────────────────────────────────────────────────────

@dataclass
class StaticFinding:
    rule_id: str
    severity: str
    file_path: str
    line_number: int
    message: str
    code_snippet: str
    source: str  # "semgrep" | "gitleaks"


@dataclass
class PolicyViolation:
    rule_id: str
    severity: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class LLMFinding:
    severity: str
    message: str
    recommendation: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class FileChangeSummary:
    """One entry per changed file — always populated regardless of feature flags."""
    file_path: str
    change_type: str  # "added" | "modified" | "deleted" | "renamed"
    summary: str      # 1-2 sentence description of what changed in this file


@dataclass
class LLMReviewResult:
    summary: str                          # overall 2-3 sentence summary
    overall_risk: str                     # "pass" | "warn" | "block"
    findings: List[LLMFinding]            # empty when FEATURE_LLM_FINDINGS=false
    file_changes: List[FileChangeSummary] # always populated
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    model: str


@dataclass
class FeatureSet:
    """Which pipeline stages are enabled for this run."""
    static_analysis: bool = False
    secret_scanning: bool = False
    policy_check: bool = False
    llm_findings: bool = False

    @property
    def any_static(self) -> bool:
        return self.static_analysis or self.secret_scanning


# ── Service interfaces ────────────────────────────────────────────────────────

class IStaticAnalyzer(ABC):
    """Runs static analysis tools against a PR diff and returns findings."""

    @abstractmethod
    def analyze(self, diff_content: str) -> List[StaticFinding]:
        ...


class IPolicyChecker(ABC):
    """Checks a PR payload against organisational policy rules."""

    @abstractmethod
    def check(self, pr_data: dict) -> List[PolicyViolation]:
        ...


class ILLMReviewer(ABC):
    """Performs an LLM-based review of a PR diff."""

    @abstractmethod
    async def review(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> LLMReviewResult:
        ...


class IGitHubService(ABC):
    """Interacts with the GitHub API on behalf of an installation."""

    @abstractmethod
    async def get_pr_diff(
        self, installation_id: int, repo_full_name: str, pr_number: int
    ) -> str:
        ...

    @abstractmethod
    async def post_review(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        event: str,  # "APPROVE" | "REQUEST_CHANGES" | "COMMENT"
    ) -> None:
        ...

    @abstractmethod
    async def create_check_run(
        self,
        installation_id: int,
        repo_full_name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> None:
        ...
