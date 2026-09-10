from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # GitHub App
    github_app_id: int = Field(..., alias="GITHUB_APP_ID")
    github_private_key_path: str = Field("./certs/private_key.pem", alias="GITHUB_PRIVATE_KEY_PATH")
    # Inline PEM content — takes precedence over GITHUB_PRIVATE_KEY_PATH.
    # Use this for cloud deployments (Databricks, etc.) where writing a file is impractical.
    github_private_key_content: str = Field("", alias="GITHUB_PRIVATE_KEY_CONTENT")
    github_webhook_secret: str = Field(..., alias="GITHUB_WEBHOOK_SECRET")

    # LLM
    llm_provider: str = Field("openai", alias="LLM_PROVIDER")
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    llm_model: str = Field("gpt-4o", alias="LLM_MODEL")

    # Databricks Foundation Model APIs (used when LLM_PROVIDER=databricks)
    databricks_host: str = Field("", alias="DATABRICKS_HOST")   # e.g. adb-1234.azuredatabricks.net
    databricks_token: str = Field("", alias="DATABRICKS_TOKEN") # Personal Access Token

    # Application
    app_host: str = Field("0.0.0.0", alias="APP_HOST")
    app_port: int = Field(8000, alias="APP_PORT")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Database
    database_url: str = Field("sqlite:///./mdlz_pr_guard.db", alias="DATABASE_URL")

    # Prompts
    prompts_dir: str = Field("./prompts", alias="PROMPTS_DIR")

    # Databricks integration
    feature_databricks_fetch: bool = Field(False, alias="FEATURE_DATABRICKS_FETCH")
    databricks_workspace_path: str = Field("/", alias="DATABRICKS_WORKSPACE_PATH")

    # ── Feature flags ─────────────────────────────────────────────────────────
    # PR summary (what changed, grouped by file) is always on.
    # All security / policy features are opt-in via environment variables.
    feature_static_analysis: bool = Field(False, alias="FEATURE_STATIC_ANALYSIS")
    feature_secret_scanning: bool = Field(False, alias="FEATURE_SECRET_SCANNING")
    feature_policy_check: bool = Field(False, alias="FEATURE_POLICY_CHECK")
    feature_llm_findings: bool = Field(False, alias="FEATURE_LLM_FINDINGS")

    # LangSmith tracing (optional)
    langsmith_tracing: bool = Field(False, alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field("", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field("mdlz-pr-guard", alias="LANGSMITH_PROJECT")

    @field_validator("github_webhook_secret")
    @classmethod
    def secret_must_not_be_empty(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("GITHUB_WEBHOOK_SECRET must be at least 8 characters")
        return v

    @field_validator("llm_provider")
    @classmethod
    def provider_must_be_supported(cls, v: str) -> str:
        supported = {"anthropic", "openai", "databricks"}
        if v.lower() not in supported:
            raise ValueError(f"LLM_PROVIDER must be one of: {supported}")
        return v.lower()


@lru_cache
def get_settings() -> Settings:
    return Settings()
