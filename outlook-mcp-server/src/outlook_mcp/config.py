"""Runtime configuration from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mcp_transport: str = Field(default="stdio", validation_alias=AliasChoices("MCP_TRANSPORT", "mcp_transport"))
    mcp_host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("MCP_HOST", "mcp_host"))
    mcp_port: int = Field(default=8000, validation_alias=AliasChoices("MCP_PORT", "mcp_port"))
    mcp_stateless_http: bool = Field(
        default=False,
        validation_alias=AliasChoices("MCP_STATELESS_HTTP", "mcp_stateless_http"),
    )

    graph_dev_token: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GRAPH_DEV_TOKEN"))

    graph_http_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        validation_alias=AliasChoices("GRAPH_HTTP_TIMEOUT", "graph_http_timeout_seconds"),
        description="Per-request timeout for Microsoft Graph HTTP calls (seconds).",
    )

    mcp_sampling_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        le=600.0,
        validation_alias=AliasChoices("MCP_SAMPLING_TIMEOUT_SECONDS", "mcp_sampling_timeout_seconds"),
        description=(
            "Max wait for the MCP client to answer sampling/createMessage. "
            "Prevents tools from hanging when the client never completes sampling (e.g. Inspector UI left open)."
        ),
    )

    enable_write_operations: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENABLE_WRITE_OPERATIONS", "enable_write_operations"),
    )

    graph_oauth_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("GRAPH_OAUTH_ENABLED", "graph_oauth_enabled"),
    )
    graph_oauth_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("GRAPH_OAUTH_CLIENT_ID", "graph_oauth_client_id"),
    )
    graph_oauth_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAPH_OAUTH_CLIENT_SECRET", "graph_oauth_client_secret"),
    )
    graph_oauth_tenant: str = Field(
        default="common",
        validation_alias=AliasChoices("GRAPH_OAUTH_TENANT", "graph_oauth_tenant"),
    )
    graph_oauth_redirect_uri: str = Field(
        default="http://127.0.0.1:8000/oauth/callback",
        validation_alias=AliasChoices("GRAPH_OAUTH_REDIRECT_URI", "graph_oauth_redirect_uri"),
    )
    graph_oauth_scopes: str = Field(
        default="Mail.Read offline_access",
        validation_alias=AliasChoices("GRAPH_OAUTH_SCOPES", "graph_oauth_scopes"),
    )
    graph_oauth_token_cache_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAPH_OAUTH_TOKEN_CACHE_PATH", "graph_oauth_token_cache_path"),
    )

    pii_redaction_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("PII_REDACTION_ENABLED", "pii_redaction_enabled"),
        description="When true, redact PII in email JSON before MCP sampling (requires [pii] extra + spaCy model).",
    )
    pii_redaction_strategy: str = Field(
        default="pseudonymize",
        validation_alias=AliasChoices("PII_REDACTION_STRATEGY", "pii_redaction_strategy"),
        description="PII replacement strategy: pseudonymize | hash | remove.",
    )
    pii_entities: str = Field(
        default="EMAIL_ADDRESS,PERSON,PHONE_NUMBER,IBAN_CODE,CREDIT_CARD,IP_ADDRESS,LOCATION",
        validation_alias=AliasChoices("PII_ENTITIES", "pii_entities"),
        description="Comma-separated Presidio entity types to detect/redact.",
    )
    pii_response_level: str = Field(
        default="full",
        validation_alias=AliasChoices("PII_RESPONSE_LEVEL", "pii_response_level"),
        description=(
            "Tool response email payload: full | minimal | redacted. "
            "`minimal` omits body_content only (from/body_preview still plaintext). "
            "`redacted` applies Presidio when available; otherwise deterministic email + display-name masking."
        ),
    )

    @field_validator("pii_redaction_strategy")
    @classmethod
    def _normalize_pii_strategy(cls, v: str) -> str:
        s = (v or "pseudonymize").lower().strip()
        if s not in ("pseudonymize", "hash", "remove"):
            return "pseudonymize"
        return s

    @field_validator("pii_response_level")
    @classmethod
    def _normalize_pii_response_level(cls, v: str) -> str:
        s = (v or "full").lower().strip()
        if s not in ("full", "minimal", "redacted"):
            return "full"
        return s


@lru_cache
def get_settings() -> Settings:
    return Settings()


def oauth_scope_list(settings: Settings) -> list[str]:
    """Space-separated scopes from settings, plus Mail.Send and Mail.ReadWrite when writes are enabled."""
    parts = [p for p in settings.graph_oauth_scopes.replace(",", " ").split() if p]
    if settings.enable_write_operations:
        if "Mail.Send" not in parts:
            parts.append("Mail.Send")
        if "Mail.ReadWrite" not in parts:
            parts.append("Mail.ReadWrite")
    return parts if parts else ["Mail.Read", "offline_access"]
