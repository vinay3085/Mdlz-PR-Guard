from collections import defaultdict
from typing import List

from app.services.interfaces import (
    FeatureSet,
    LLMFinding,
    LLMReviewResult,
    PolicyViolation,
    StaticFinding,
)

_SEV_ICON = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🔵",
    "info":     "⚪",
}

_RISK_BADGE = {
    "pass":  "✅ **PASS** — No blocking issues found",
    "warn":  "⚠️ **WARN** — Issues found; review recommended before merge",
    "block": "❌ **BLOCK** — Critical/high severity issues must be resolved before merge",
}

_CHANGE_ICON = {
    "added":    "➕",
    "modified": "✏️",
    "deleted":  "🗑️",
    "renamed":  "🔀",
}


class CommentComposer:
    """
    Assembles the structured PR review comment and GitHub check-run summary.

    Sections are conditionally rendered based on FeatureSet and whether
    the section has any content — the comment is never cluttered with
    empty headings.
    """

    def compose(
        self,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        llm_result: LLMReviewResult,
        features: FeatureSet,
    ) -> tuple[str, str]:
        """Returns (pr_review_body, check_run_summary)."""
        lines: List[str] = []

        # ── Header & overall risk ────────────────────────────────────────────
        lines.append("# PR Change Report\n")

        if features.llm_findings:
            lines.append(_RISK_BADGE.get(llm_result.overall_risk, _RISK_BADGE["warn"]))
            lines.append("")

        # ── Summary ──────────────────────────────────────────────────────────
        lines.append("## Summary")
        lines.append(llm_result.summary)
        lines.append("")

        # ── Changed Files table ──────────────────────────────────────────────
        if llm_result.file_changes:
            lines.append("## Changed Files")
            lines.append("")
            lines.append("| File | Change | Description |")
            lines.append("|------|--------|-------------|")
            for fc in llm_result.file_changes:
                icon = _CHANGE_ICON.get(fc.change_type.lower(), "✏️")
                change_label = f"{icon} {fc.change_type.capitalize()}"
                # Escape pipe characters in description to avoid breaking the table
                desc = fc.summary.replace("|", "\\|")
                lines.append(f"| `{fc.file_path}` | {change_label} | {desc} |")
            lines.append("")

        # ── Static analysis findings (grouped by file) ────────────────────────
        if static_findings:
            lines.append("## Static Analysis Findings")
            lines.append(
                f"*{len(static_findings)} finding(s) from "
                f"{'Semgrep' if features.static_analysis else ''}"
                f"{' + ' if features.static_analysis and features.secret_scanning else ''}"
                f"{'Gitleaks' if features.secret_scanning else ''}*"
            )
            lines.append("")
            for file_path, file_findings in _group_static_by_file(static_findings).items():
                lines.append(f"### `{file_path}`")
                for f in file_findings:
                    icon = _SEV_ICON.get(f.severity, "⚪")
                    lines.append(
                        f"- {icon} **[{f.severity.upper()}]** line {f.line_number} "
                        f"— `{f.rule_id}` ({f.source})"
                    )
                    lines.append(f"  {f.message}")
                    if f.code_snippet:
                        lines.append(f"  ```\n  {f.code_snippet}\n  ```")
                lines.append("")

        # ── Policy violations ────────────────────────────────────────────────
        if policy_violations:
            lines.append("## Policy Violations")
            lines.append(f"*{len(policy_violations)} violation(s)*")
            lines.append("")
            for v in policy_violations:
                icon = _SEV_ICON.get(v.severity, "⚪")
                lines.append(f"- {icon} **[{v.rule_id}]** {v.message}")
            lines.append("")

        # ── LLM security findings (grouped by file) ──────────────────────────
        if llm_result.findings:
            lines.append("## Security Analysis")
            lines.append(f"*{len(llm_result.findings)} finding(s) from AI analysis*")
            lines.append("")
            file_findings, no_file = _group_llm_by_file(llm_result.findings)
            for file_path, findings in file_findings.items():
                lines.append(f"### `{file_path}`")
                for f in findings:
                    icon = _SEV_ICON.get(f.severity, "⚪")
                    loc = f" line {f.line_number}" if f.line_number else ""
                    lines.append(f"- {icon} **[{f.severity.upper()}]**{loc} — {f.message}")
                    if f.recommendation:
                        lines.append(f"  > **Recommendation:** {f.recommendation}")
                lines.append("")
            if no_file:
                lines.append("### General")
                for f in no_file:
                    icon = _SEV_ICON.get(f.severity, "⚪")
                    lines.append(f"- {icon} **[{f.severity.upper()}]** {f.message}")
                    if f.recommendation:
                        lines.append(f"  > **Recommendation:** {f.recommendation}")
                lines.append("")

        # ── Footer ───────────────────────────────────────────────────────────
        total = len(static_findings) + len(policy_violations) + len(llm_result.findings)
        active_features = _active_feature_names(features)
        lines.append("---")
        #lines.append(
        #    f"*PR Guard | Model: `{llm_result.model}` | "
        #    f"Active: {active_features} | "
        #    f"{total} finding(s)*"
        #)

        review_body = "\n".join(lines)
        check_summary = (
            f"{len(llm_result.file_changes)} file(s) changed — "
            f"Static: {len(static_findings)}, "
            f"Policy: {len(policy_violations)}, "
            f"AI: {len(llm_result.findings)} | "
            f"Risk: {llm_result.overall_risk.upper()}"
        )
        return review_body, check_summary

    def get_review_event(self, llm_result: LLMReviewResult, features: FeatureSet) -> str:
        # Only approve/request changes when security analysis is active
        if not features.llm_findings:
            return "COMMENT"
        if llm_result.overall_risk == "block":
            return "REQUEST_CHANGES"
        if llm_result.overall_risk == "pass":
            return "APPROVE"
        return "COMMENT"

    def get_check_conclusion(self, llm_result: LLMReviewResult, features: FeatureSet) -> str:
        if not features.llm_findings:
            return "neutral"
        mapping = {"block": "failure", "warn": "neutral", "pass": "success"}
        return mapping.get(llm_result.overall_risk, "neutral")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _group_static_by_file(findings: List[StaticFinding]) -> dict:
    grouped: dict = defaultdict(list)
    for f in findings:
        grouped[f.file_path].append(f)
    return dict(grouped)


def _group_llm_by_file(findings: List[LLMFinding]) -> tuple[dict, List[LLMFinding]]:
    grouped: dict = defaultdict(list)
    no_file: List[LLMFinding] = []
    for f in findings:
        if f.file_path:
            grouped[f.file_path].append(f)
        else:
            no_file.append(f)
    return dict(grouped), no_file


def _active_feature_names(features: FeatureSet) -> str:
    names = ["Summary"]
    if features.static_analysis:
        names.append("Semgrep")
    if features.secret_scanning:
        names.append("Gitleaks")
    if features.policy_check:
        names.append("Policy")
    if features.llm_findings:
        names.append("Security AI")
    return ", ".join(names)
