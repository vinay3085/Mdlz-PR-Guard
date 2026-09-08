import json
import logging
from pathlib import Path
from typing import List

import anthropic
import openai
from langsmith import traceable
from langsmith.wrappers import wrap_anthropic, wrap_openai

from app.config import Settings
from app.services.interfaces import (
    FeatureSet,
    FileChangeSummary,
    ILLMReviewer,
    LLMFinding,
    LLMReviewResult,
    PolicyViolation,
    StaticFinding,
)

logger = logging.getLogger(__name__)

_MAX_DIFF_CHARS = 60_000
_MAX_TOKENS = 8192


def _build_enabled_analyses(
    features: FeatureSet,
    static_findings: List[StaticFinding],
    policy_violations: List[PolicyViolation],
) -> str:
    """Builds the human-readable enabled-analyses block injected into the user prompt."""
    lines = ["- PR Change Summary (file-by-file description): **ENABLED** (always)"]

    if features.static_analysis and features.secret_scanning:
        sa_label = "Static Analysis (Semgrep) + Secret Scanning (Gitleaks)"
    elif features.static_analysis:
        sa_label = "Static Analysis (Semgrep)"
    elif features.secret_scanning:
        sa_label = "Secret Scanning (Gitleaks)"
    else:
        sa_label = None

    if sa_label:
        lines.append(f"- {sa_label}: **ENABLED** — {len(static_findings)} finding(s) provided below")
    else:
        lines.append("- Static Analysis / Secret Scanning: DISABLED")

    if features.policy_check:
        lines.append(
            f"- Org Policy Check: **ENABLED** — {len(policy_violations)} violation(s) provided below"
        )
    else:
        lines.append("- Org Policy Check: DISABLED")

    if features.llm_findings:
        lines.append(
            "- Security Analysis (LLM): **ENABLED** — identify vulnerabilities, "
            "populate 'findings', set 'overall_risk'"
        )
    else:
        lines.append(
            "- Security Analysis (LLM): DISABLED — do NOT add any 'findings'; "
            "set 'overall_risk' to 'pass'"
        )

    return "\n".join(lines)


def _parse_file_changes(data: dict) -> List[FileChangeSummary]:
    return [
        FileChangeSummary(
            file_path=fc.get("file_path", ""),
            change_type=fc.get("change_type", "modified"),
            summary=fc.get("summary", ""),
        )
        for fc in data.get("file_changes", [])
        if fc.get("file_path")
    ]


def _parse_findings(data: dict) -> List[LLMFinding]:
    return [
        LLMFinding(
            severity=f.get("severity", "medium"),
            file_path=f.get("file_path"),
            line_number=f.get("line_number"),
            message=f.get("message", ""),
            recommendation=f.get("recommendation", ""),
        )
        for f in data.get("findings", [])
    ]


class AnthropicLLMReviewer(ILLMReviewer):
    """
    LLM-based reviewer using the Anthropic Claude API.
    Implements ILLMReviewer — swappable without pipeline changes (OCP).
    """

    def __init__(self, settings: Settings) -> None:
        self._client = wrap_anthropic(anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key))
        self._model = settings.llm_model
        self._prompts_dir = Path(settings.prompts_dir)

    def _load_prompt(self, filename: str) -> str:
        return (self._prompts_dir / filename).read_text(encoding="utf-8")

    def _build_user_prompt(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> str:
        template = self._load_prompt("user_prompt_template.txt")

        static_summary = "\n".join(
            f"- [{f.severity.upper()}] {f.source}/{f.rule_id} "
            f"at {f.file_path}:{f.line_number} — {f.message}"
            for f in static_findings
        ) or "None"

        policy_summary = "\n".join(
            f"- [{v.severity.upper()}] {v.rule_id}: {v.message}"
            for v in policy_violations
        ) or "None"

        truncated_diff = diff[:_MAX_DIFF_CHARS]
        if len(diff) > _MAX_DIFF_CHARS:
            truncated_diff += f"\n\n[... diff truncated at {_MAX_DIFF_CHARS} chars ...]"

        return template.format(
            enabled_analyses=_build_enabled_analyses(features, static_findings, policy_violations),
            diff=truncated_diff,
            static_findings=static_summary,
            policy_violations=policy_summary,
        )

    @traceable(run_type="chain", name="pr-security-review-anthropic", tags=["pr-review", "security"])
    async def review(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> LLMReviewResult:
        system_prompt = self._load_prompt("system_prompt.txt")
        user_prompt = self._build_user_prompt(diff, static_findings, policy_violations, features)

        logger.info("Calling %s for LLM review (features: %s)", self._model, vars(features))

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            response = await stream.get_final_message()

        raw_text = ""
        for block in response.content:
            if block.type == "text":
                raw_text = block.text
                break

        data = self._parse_json_response(raw_text)

        return LLMReviewResult(
            summary=data.get("overall_summary", raw_text[:500]),
            overall_risk=data.get("overall_risk", "pass"),
            findings=_parse_findings(data),
            file_changes=_parse_file_changes(data),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
            model=self._model,
        )

    def _parse_json_response(self, text: str) -> dict:
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            logger.warning("Anthropic returned non-JSON response; using fallback defaults")
        return {}


class OpenAILLMReviewer(ILLMReviewer):
    """
    LLM-based reviewer using the OpenAI API.
    Implements ILLMReviewer — interchangeable with AnthropicLLMReviewer (LSP + OCP).
    Uses JSON mode to guarantee structured output.
    """

    def __init__(self, settings: Settings) -> None:
        self._client = wrap_openai(openai.AsyncOpenAI(api_key=settings.openai_api_key))
        self._model = settings.llm_model
        self._prompts_dir = Path(settings.prompts_dir)

    def _load_prompt(self, filename: str) -> str:
        return (self._prompts_dir / filename).read_text(encoding="utf-8")

    def _build_user_prompt(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> str:
        template = self._load_prompt("user_prompt_template.txt")

        static_summary = "\n".join(
            f"- [{f.severity.upper()}] {f.source}/{f.rule_id} "
            f"at {f.file_path}:{f.line_number} — {f.message}"
            for f in static_findings
        ) or "None"

        policy_summary = "\n".join(
            f"- [{v.severity.upper()}] {v.rule_id}: {v.message}"
            for v in policy_violations
        ) or "None"

        truncated_diff = diff[:_MAX_DIFF_CHARS]
        if len(diff) > _MAX_DIFF_CHARS:
            truncated_diff += f"\n\n[... diff truncated at {_MAX_DIFF_CHARS} chars ...]"

        return template.format(
            enabled_analyses=_build_enabled_analyses(features, static_findings, policy_violations),
            diff=truncated_diff,
            static_findings=static_summary,
            policy_violations=policy_summary,
        )

    @traceable(run_type="chain", name="pr-security-review-openai", tags=["pr-review", "security"])
    async def review(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> LLMReviewResult:
        system_prompt = self._load_prompt("system_prompt.txt")
        user_prompt = self._build_user_prompt(diff, static_findings, policy_violations, features)

        logger.info("Calling %s for LLM review (features: %s)", self._model, vars(features))

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = response.choices[0].message.content or ""
        data = self._parse_json_response(raw_text)

        usage = response.usage
        cached = 0
        if usage and hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

        return LLMReviewResult(
            summary=data.get("overall_summary", raw_text[:500]),
            overall_risk=data.get("overall_risk", "pass"),
            findings=_parse_findings(data),
            file_changes=_parse_file_changes(data),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=cached,
            model=self._model,
        )

    def _parse_json_response(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("OpenAI returned non-JSON response; using fallback defaults")
        return {}


class DatabricksLLMReviewer(ILLMReviewer):
    """
    LLM-based reviewer using Databricks Foundation Model APIs (OpenAI-compatible endpoint).
    Default model: databricks-meta-llama-3-3-70b-instruct (free Llama 3.3 tier).

    Implements ILLMReviewer — fully interchangeable with other providers (LSP + OCP).
    Uses prompt-based JSON extraction rather than response_format, because Llama models
    served via Databricks do not guarantee strict JSON mode.
    """

    def __init__(self, settings: Settings) -> None:
        base_url = f"https://{settings.databricks_host}/serving-endpoints"
        self._client = wrap_openai(
            openai.AsyncOpenAI(
                api_key=settings.databricks_token,
                base_url=base_url,
            )
        )
        self._model = settings.llm_model
        self._prompts_dir = Path(settings.prompts_dir)

    def _load_prompt(self, filename: str) -> str:
        return (self._prompts_dir / filename).read_text(encoding="utf-8")

    def _build_user_prompt(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> str:
        template = self._load_prompt("user_prompt_template.txt")

        static_summary = "\n".join(
            f"- [{f.severity.upper()}] {f.source}/{f.rule_id} "
            f"at {f.file_path}:{f.line_number} — {f.message}"
            for f in static_findings
        ) or "None"

        policy_summary = "\n".join(
            f"- [{v.severity.upper()}] {v.rule_id}: {v.message}"
            for v in policy_violations
        ) or "None"

        truncated_diff = diff[:_MAX_DIFF_CHARS]
        if len(diff) > _MAX_DIFF_CHARS:
            truncated_diff += f"\n\n[... diff truncated at {_MAX_DIFF_CHARS} chars ...]"

        return template.format(
            enabled_analyses=_build_enabled_analyses(features, static_findings, policy_violations),
            diff=truncated_diff,
            static_findings=static_summary,
            policy_violations=policy_summary,
        )

    @traceable(run_type="chain", name="pr-security-review-databricks", tags=["pr-review", "security"])
    async def review(
        self,
        diff: str,
        static_findings: List[StaticFinding],
        policy_violations: List[PolicyViolation],
        features: FeatureSet,
    ) -> LLMReviewResult:
        system_prompt = self._load_prompt("system_prompt.txt")
        user_prompt = self._build_user_prompt(diff, static_findings, policy_violations, features)

        logger.info("Calling Databricks %s for LLM review (features: %s)", self._model, vars(features))

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        raw_text = response.choices[0].message.content or ""
        data = self._parse_json_response(raw_text)

        usage = response.usage
        return LLMReviewResult(
            summary=data.get("overall_summary", raw_text[:500]),
            overall_risk=data.get("overall_risk", "pass"),
            findings=_parse_findings(data),
            file_changes=_parse_file_changes(data),
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cached_tokens=0,  # Databricks Foundation Model APIs do not expose prompt caching
            model=self._model,
        )

    def _parse_json_response(self, text: str) -> dict:
        # Llama may wrap the JSON in markdown fences — strip them and find the outermost object
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            logger.warning("Databricks Llama returned non-JSON response; using fallback defaults")
        return {}
