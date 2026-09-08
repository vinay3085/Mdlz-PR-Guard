from sqlalchemy.orm import Session
from app.models.database import UsageLedger
from app.repositories.base import BaseRepository
from app.services.interfaces import LLMReviewResult

# Token pricing per 1M tokens (USD) — verify current rates at provider consoles
_PRICING: dict[str, dict[str, float]] = {
    # Anthropic models
    "claude-opus-5":    {"input": 5.00,  "output": 25.00, "cache_read": 0.50},
    "claude-opus-4-8":  {"input": 5.00,  "output": 25.00, "cache_read": 0.50},
    "claude-sonnet-5":  {"input": 2.00,  "output": 10.00, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.00,  "output": 5.00,  "cache_read": 0.10},
    # OpenAI models
    "gpt-4o":           {"input": 2.50,  "output": 10.00, "cache_read": 1.25},
    "gpt-4o-mini":      {"input": 0.15,  "output": 0.60,  "cache_read": 0.075},
    "o1":               {"input": 15.00, "output": 60.00, "cache_read": 7.50},
    "o3-mini":          {"input": 1.10,  "output": 4.40,  "cache_read": 0.55},
}
_DEFAULT_PRICING = {"input": 5.00, "output": 25.00, "cache_read": 0.50}


class UsageLedgerRepository(BaseRepository[UsageLedger]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, UsageLedger)

    def record_llm_usage(
        self, pr_review_id: int, llm_result: LLMReviewResult, latency_ms: int
    ) -> UsageLedger:
        pricing = _PRICING.get(llm_result.model, _DEFAULT_PRICING)

        cost_usd = (
            (llm_result.input_tokens / 1_000_000) * pricing["input"]
            + (llm_result.output_tokens / 1_000_000) * pricing["output"]
            + (llm_result.cached_tokens / 1_000_000) * pricing["cache_read"]
        )

        entry = UsageLedger(
            pr_review_id=pr_review_id,
            model=llm_result.model,
            input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
            cached_tokens=llm_result.cached_tokens,
            cost_usd=round(cost_usd, 6),
            latency_ms=latency_ms,
        )
        self.add(entry)
        self.commit()
        return entry
