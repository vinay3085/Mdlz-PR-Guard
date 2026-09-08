import json
import logging
import os
import subprocess
import tempfile
from typing import List

from app.services.interfaces import IStaticAnalyzer, StaticFinding

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = 120  # seconds


class SemgrepAnalyzer(IStaticAnalyzer):
    """Runs Semgrep against the PR diff and returns findings."""

    def analyze(self, diff_content: str) -> List[StaticFinding]:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".diff", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(diff_content)
            diff_file = tmp.name

        try:
            result = subprocess.run(
                ["semgrep", "--config", "auto", "--json", diff_file],
                capture_output=True,
                text=True,
                encoding="utf-8",   # force UTF-8; without this Windows defaults to cp1252
                errors="replace",   # replace undecodable bytes rather than crashing
                timeout=_SUBPROCESS_TIMEOUT,
                # Never use shell=True with user-derived paths
            )
            return self._parse(result.stdout)
        except FileNotFoundError:
            logger.warning("semgrep not found on PATH — skipping Semgrep analysis")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("Semgrep timed out after %ds", _SUBPROCESS_TIMEOUT)
            return []
        finally:
            os.unlink(diff_file)

    def _parse(self, stdout: str) -> List[StaticFinding]:
        if not stdout:
            return []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("Semgrep produced invalid JSON output")
            return []

        findings = []
        for r in data.get("results", []):
            extra = r.get("extra", {})
            findings.append(
                StaticFinding(
                    rule_id=r.get("check_id", "semgrep.unknown"),
                    severity=extra.get("severity", "medium").lower(),
                    file_path=r.get("path", ""),
                    line_number=r.get("start", {}).get("line", 0),
                    message=extra.get("message", ""),
                    code_snippet=(extra.get("lines", "") or "")[:500],
                    source="semgrep",
                )
            )
        return findings


class GitleaksAnalyzer(IStaticAnalyzer):
    """Runs Gitleaks against the PR diff to detect secrets."""

    def analyze(self, diff_content: str) -> List[StaticFinding]:
        with tempfile.TemporaryDirectory() as tmpdir:
            diff_file = os.path.join(tmpdir, "changes.diff")
            report_file = os.path.join(tmpdir, "report.json")

            with open(diff_file, "w", encoding="utf-8") as f:
                f.write(diff_content)

            try:
                subprocess.run(
                    [
                        "gitleaks",
                        "detect",
                        "--source", tmpdir,
                        "--no-git",
                        "--report-format", "json",
                        "--report-path", report_file,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                return self._parse(report_file)
            except FileNotFoundError:
                logger.warning("gitleaks not found on PATH — skipping Gitleaks analysis")
                return []
            except subprocess.TimeoutExpired:
                logger.warning("Gitleaks timed out")
                return []

    def _parse(self, report_file: str) -> List[StaticFinding]:
        if not os.path.exists(report_file):
            return []
        try:
            with open(report_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        if not isinstance(data, list):
            return []

        findings = []
        for leak in data:
            findings.append(
                StaticFinding(
                    rule_id=leak.get("RuleID", "gitleaks.secret"),
                    severity="critical",
                    file_path=leak.get("File", ""),
                    line_number=leak.get("StartLine", 0),
                    message=f"Secret detected: {leak.get('Description', 'Potential credential or key')}",
                    code_snippet=(leak.get("Match", "") or "")[:200],
                    source="gitleaks",
                )
            )
        return findings


class CompositeStaticAnalyzer(IStaticAnalyzer):
    """
    Runs multiple IStaticAnalyzer implementations and merges their results.
    Follows the Open/Closed Principle — add new tools without modifying this class.
    """

    def __init__(self, analyzers: List[IStaticAnalyzer]) -> None:
        self._analyzers = analyzers

    def analyze(self, diff_content: str) -> List[StaticFinding]:
        all_findings: List[StaticFinding] = []
        for analyzer in self._analyzers:
            all_findings.extend(analyzer.analyze(diff_content))
        return self._deduplicate(all_findings)

    def _deduplicate(self, findings: List[StaticFinding]) -> List[StaticFinding]:
        seen: set = set()
        unique: List[StaticFinding] = []
        for f in findings:
            key = (f.source, f.rule_id, f.file_path, f.line_number)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique
