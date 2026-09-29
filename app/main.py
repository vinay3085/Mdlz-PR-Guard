import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path  # noqa: F401 — must be imported before RunTree.model_rebuild()

# pydantic 2.9 cannot resolve the `Path` forward reference inside LangSmith's RunTree
# until pathlib.Path is present in the global namespace and model_rebuild() is called.
from langsmith.run_trees import RunTree as _RunTree
_RunTree.model_rebuild()

from fastapi import BackgroundTasks, FastAPI, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.handlers.webhook_handler import WebhookHandler
from app.models.database import Base
from app.repositories.findings_repo import FindingsRepository
from app.repositories.installation_repo import InstallationRepository
from app.repositories.pr_review_repo import PRReviewRepository
from app.repositories.usage_ledger_repo import UsageLedgerRepository
from app.services.comment_composer import CommentComposer
from app.services.github_auth import GitHubAuthService
from app.services.github_service import GitHubService
from app.services.llm_service import AnthropicLLMReviewer, DatabricksLLMReviewer, OpenAILLMReviewer
from app.services.interfaces import FeatureSet, ILLMReviewer
from app.services.policy_checker import OrgPolicyChecker
from app.services.static_analysis_service import (
    CompositeStaticAnalyzer,
    GitleaksAnalyzer,
    SemgrepAnalyzer,
)
from app.services.databricks_analyzer import DatabricksWorkspaceAnalyzer
from app.utils.signature_verifier import verify_webhook_signature

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Force-clear the lru_cache so every (re)start re-reads .env from disk.
    # Without this, uvicorn --reload reuses the old cached Settings object.
    get_settings.cache_clear()
    settings = get_settings()

    # ── Log effective LLM config immediately so misconfiguration is obvious ──
    provider = settings.llm_provider
    model = settings.llm_model
    anthropic_key_set = bool(settings.anthropic_api_key)
    openai_key_set = bool(settings.openai_api_key)
    databricks_configured = bool(settings.databricks_host and settings.databricks_token)
    logger.info(
        "LLM config: provider=%s  model=%s  anthropic_key=%s  openai_key=%s  databricks=%s",
        provider, model,
        "SET" if anthropic_key_set else "NOT SET ⚠️",
        "SET" if openai_key_set else "NOT SET ⚠️",
        "SET" if databricks_configured else "NOT SET",
    )
    if provider == "anthropic" and not anthropic_key_set:
        print("ANTHROPIC_API_KEY is empty but LLM_PROVIDER=anthropic — LLM calls will fail")
        logger.error("ANTHROPIC_API_KEY is empty but LLM_PROVIDER=anthropic — LLM calls will fail")
    if provider == "openai" and not openai_key_set:
        logger.error("OPENAI_API_KEY is empty but LLM_PROVIDER=openai — LLM calls will fail")
    if provider == "databricks" and not databricks_configured:
        logger.error("DATABRICKS_HOST/DATABRICKS_TOKEN not set but LLM_PROVIDER=databricks — LLM calls will fail")

    # ── Feature flags ─────────────────────────────────────────────────────────
    logger.info(
        "Features: static_analysis=%s  secret_scanning=%s  policy_check=%s  llm_findings=%s",
        settings.feature_static_analysis,
        settings.feature_secret_scanning,
        settings.feature_policy_check,
        settings.feature_llm_findings,
    )

    # ── LangSmith tracing ─────────────────────────────────────────────────────
    # pydantic-settings reads .env into Settings but does NOT populate os.environ.
    # LangSmith's SDK reads directly from os.environ, so we bridge the gap here.
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        logger.info("LangSmith tracing enabled — project: %s", settings.langsmith_project)
    else:
        logger.info("LangSmith tracing disabled (set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable)")

    # ── Wire the LLM reviewer once at startup and store on app.state ─────────
    app.state.llm_reviewer = _build_llm_reviewer(settings)

    # ── Database ──────────────────────────────────────────────────────────────
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, autoflush=True)
    logger.info("Database ready at %s", settings.database_url)

    # ── Validate GitHub App credentials ───────────────────────────────────────
    auth_service = GitHubAuthService(
        app_id=settings.github_app_id,
        private_key_path=settings.github_private_key_path,
        private_key_content=settings.github_private_key_content,
    )
    try:
        await auth_service.validate_credentials()
    except Exception as exc:
        logger.error("GitHub App credential check failed: %s", exc)

    yield
    engine.dispose()
    logger.info("Database connection closed")


app = FastAPI(
    title="Mdlz PR Guard",
    description="AI-Powered PR Security & Org Policy Scanner",
    version="1.0.0",
    lifespan=lifespan,
)


def _build_llm_reviewer(settings) -> ILLMReviewer:
    """
    Selects the concrete ILLMReviewer implementation based on LLM_PROVIDER.
    Adding a new provider requires only a new branch here — no other changes (OCP).
    """
    if settings.llm_provider == "openai":
        logger.info("Using OpenAI LLM reviewer (model=%s)", settings.llm_model)
        return OpenAILLMReviewer(settings)
    if settings.llm_provider == "databricks":
        logger.info(
            "Using Databricks LLM reviewer (host=%s  model=%s)",
            settings.databricks_host, settings.llm_model,
        )
        return DatabricksLLMReviewer(settings)
    logger.info("Using Anthropic LLM reviewer (model=%s)", settings.llm_model)
    return AnthropicLLMReviewer(settings)


def _build_features(settings) -> FeatureSet:
    return FeatureSet(
        static_analysis=settings.feature_static_analysis,
        secret_scanning=settings.feature_secret_scanning,
        policy_check=settings.feature_policy_check,
        llm_findings=settings.feature_llm_findings,
    )


def _build_handler(request: Request) -> WebhookHandler:
    """
    Factory that wires concrete implementations into WebhookHandler (DIP).
    The LLM reviewer is reused from app.state (wired once at startup).
    Only the analyzers for enabled features are included in the composite.
    A new SQLAlchemy session is created per webhook invocation.
    """
    settings = get_settings()
    features = _build_features(settings)
    session = request.app.state.session_factory()

    auth_service = GitHubAuthService(
        app_id=settings.github_app_id,
        private_key_path=settings.github_private_key_path,
        private_key_content=settings.github_private_key_content,
    )
    github_service = GitHubService(auth_service)

    # Only include analyzers for features that are enabled
    analyzers = []
    if features.static_analysis:
        analyzers.append(SemgrepAnalyzer())
    if features.secret_scanning:
        analyzers.append(GitleaksAnalyzer())
    # If Databricks workspace fetch is enabled, include the workspace analyzer
    if settings.feature_databricks_fetch:
        analyzers.append(DatabricksWorkspaceAnalyzer())

    return WebhookHandler(
        github_service=github_service,
        static_analyzer=CompositeStaticAnalyzer(analyzers),
        policy_checker=OrgPolicyChecker(),
        llm_reviewer=request.app.state.llm_reviewer,  # reuse startup-wired instance
        comment_composer=CommentComposer(),
        pr_review_repo=PRReviewRepository(session),
        findings_repo=FindingsRepository(session),
        usage_ledger_repo=UsageLedgerRepository(session),
        installation_repo=InstallationRepository(session),
        features=features,
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "mdlz-pr-guard"}


@app.post("/webhook", tags=["webhook"])
async def webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """
    Entry point for all GitHub App webhook deliveries.

    1. Verifies HMAC-SHA256 signature immediately (timing-safe).
    2. Returns HTTP 200 to GitHub within milliseconds.
    3. Runs the full review pipeline in a FastAPI BackgroundTask.
    """
    settings = get_settings()
    body = await verify_webhook_signature(request, settings.github_webhook_secret)

    payload = json.loads(body)
    event_type = request.headers.get("X-GitHub-Event", "")

    handler = _build_handler(request)

    if event_type == "installation":
        background_tasks.add_task(handler.handle_installation, payload)
    elif event_type == "pull_request":
        background_tasks.add_task(handler.handle_pull_request, payload)
    else:
        logger.debug("No handler for event type: %s", event_type)

    return {"status": "accepted"}
