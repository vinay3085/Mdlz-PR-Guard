import logging
import os
import subprocess
import tempfile
from typing import List

from app.services.interfaces import IStaticAnalyzer, StaticFinding
from app.services.static_analysis_service import SemgrepAnalyzer, GitleaksAnalyzer
from app.services.databricks_service import DatabricksService
from app.config import get_settings

logger = logging.getLogger(__name__)


class DatabricksWorkspaceAnalyzer(IStaticAnalyzer):
    """Fetches files from a Databricks workspace and runs Semgrep + Gitleaks on them."""

    def analyze(self, diff_content: str) -> List[StaticFinding]:
        settings = get_settings()
        workspace_path = settings.databricks_workspace_path

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                dbs = DatabricksService()
                dbs.export_path_to_dir(workspace_path, tmpdir)
            except Exception as e:
                logger.warning("Databricks fetch failed: %s", e)
                return []

            findings: List[StaticFinding] = []
            # Run Semgrep against the exported directory
            try:
                result = subprocess.run(
                    ["semgrep", "--config", "auto", "--json", tmpdir],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                findings.extend(SemgrepAnalyzer()._parse(result.stdout))
            except FileNotFoundError:
                logger.warning("semgrep not found on PATH — skipping Semgrep analysis")
            except subprocess.TimeoutExpired:
                logger.warning("Semgrep timed out on Databricks export")

            # Run Gitleaks against the exported directory and parse JSON report
            try:
                report_file = os.path.join(tmpdir, "gitleaks_report.json")
                subprocess.run(
                    [
                        "gitleaks",
                        "detect",
                        "--source",
                        tmpdir,
                        "--no-git",
                        "--report-format",
                        "json",
                        "--report-path",
                        report_file,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                # Parse the report file using existing parser logic
                gitleaks_findings = GitleaksAnalyzer()._parse(report_file)
                findings.extend(gitleaks_findings)
            except FileNotFoundError:
                logger.warning("gitleaks not found on PATH — skipping Gitleaks analysis")
            except subprocess.TimeoutExpired:
                logger.warning("Gitleaks timed out on Databricks export")

            # Return combined findings (Semgrep + Gitleaks)
            return findings
