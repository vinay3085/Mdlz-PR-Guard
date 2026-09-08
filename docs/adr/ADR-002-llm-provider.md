# ADR-002: LLM Provider Selection

**Status:** Accepted  
**Date:** 2026-08-17  
**Updated:** 2026-08-17 — OpenAI added as a supported provider  
**Deciders:** Platform Engineering PoC team

---

## Context

The PR scanner requires an LLM to perform contextual security analysis beyond what static tools can detect. The HLD listed "OpenAI gpt-4o or similar" as the default. The implementation must support multiple providers without requiring code changes when switching.

## Decision

Support both **Anthropic Claude** and **OpenAI** as first-class providers, switchable via `LLM_PROVIDER` and `LLM_MODEL` environment variables. Default is `anthropic` / `claude-opus-5`.

| Setting | Anthropic | OpenAI |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `openai` |
| `LLM_MODEL` | `claude-opus-5` / `claude-sonnet-5` / `claude-haiku-4-5` | `gpt-4o` / `gpt-4o-mini` / `o1` / `o3-mini` |
| API key env var | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` |

## Interface Design (SOLID — Open/Closed Principle)

The `ILLMReviewer` abstract interface in `app/services/interfaces.py` means both providers are hot-swappable — the pipeline never knows which is active:

```
ILLMReviewer
├── AnthropicLLMReviewer   (adaptive thinking + streaming via Anthropic SDK)
└── OpenAILLMReviewer      (JSON mode via OpenAI SDK)
```

Provider selection lives in `_build_llm_reviewer()` in `app/main.py`. Adding a third provider (e.g. AWS Bedrock, Google Gemini) requires only:
1. A new class implementing `ILLMReviewer`
2. A new `elif` branch in `_build_llm_reviewer()`

## Provider Comparison

| Capability | Anthropic claude-opus-5 | OpenAI gpt-4o |
|---|---|---|
| Structured output | JSON extracted from text + adaptive thinking | JSON mode (`response_format`) — guaranteed valid JSON |
| Extended reasoning | `thinking: {type: "adaptive"}` | Not supported on gpt-4o (use `o1`/`o3` series) |
| Prompt caching | Yes (`cache_read_input_tokens` in response) | Yes (`prompt_tokens_details.cached_tokens`) |
| Streaming | Yes (used by AnthropicLLMReviewer) | Yes (not used — output size fits within timeout) |
| Pricing (approx.) | $5/1M input, $25/1M output | $2.50/1M input, $10/1M output |

## Consequences

- **Positive:** Teams can switch providers with a single env var change; no code changes
- **Positive:** OpenAI JSON mode guarantees valid JSON — no regex extraction fallback needed
- **Positive:** Anthropic's adaptive thinking improves detection quality on complex diffs
- **Negative:** Two SDK dependencies (`anthropic` + `openai`) both installed, even when only one is used
- **Negative:** Output quality varies between providers; system prompt has been tested primarily with Claude

## Alternatives Considered

- **Single provider only:** Rejected — org may have existing contracts with either vendor
- **LangChain abstraction:** Rejected — adds a heavy dependency and obscures provider-specific features (adaptive thinking, JSON mode)
- **AWS Bedrock:** Future option; both Claude and GPT-4o are available there; API-compatible with both SDKs
