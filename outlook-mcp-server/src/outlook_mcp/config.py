"""Runtime configuration from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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

    mcp_enabled_tools: str = Field(
        default="",
        validation_alias=AliasChoices("MCP_ENABLED_TOOLS", "mcp_enabled_tools"),
        description="Comma-separated allowlist of tool names; empty = every tool the configuration allows.",
    )
    mcp_disabled_tools: str = Field(
        default="",
        validation_alias=AliasChoices("MCP_DISABLED_TOOLS", "mcp_disabled_tools"),
        description="Comma-separated tool names to remove (applied after MCP_ENABLED_TOOLS).",
    )

    mcp_instructions_append: str = Field(
        default="",
        validation_alias=AliasChoices("MCP_INSTRUCTIONS_APPEND", "mcp_instructions_append"),
        description="Deployment-specific text appended to the generated server instructions (capped at 4000 chars).",
        repr=False,
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
        # No offline_access/openid/profile here: MSAL adds them and rejects them as input.
        # They are still granted on the Entra ID app registration.
        default="Mail.Read",
        validation_alias=AliasChoices("GRAPH_OAUTH_SCOPES", "graph_oauth_scopes"),
    )
    graph_oauth_token_cache_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAPH_OAUTH_TOKEN_CACHE_PATH", "graph_oauth_token_cache_path"),
    )

    # application: client_credentials + /users/... vs delegated: /me
    graph_auth_mode: str = Field(
        default="delegated",
        validation_alias=AliasChoices("GRAPH_AUTH_MODE", "graph_auth_mode"),
        description="delegated (default) uses /me; application uses /users/{mailbox} with app-only tokens.",
    )
    graph_tenant_id: str = Field(
        default="",
        validation_alias=AliasChoices("GRAPH_TENANT_ID", "graph_tenant_id"),
        description="Tenant for client_credentials; if empty, GRAPH_OAUTH_TENANT is used.",
    )
    graph_application_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("GRAPH_APPLICATION_CLIENT_ID", "graph_application_client_id"),
    )
    graph_application_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GRAPH_APPLICATION_CLIENT_SECRET", "graph_application_client_secret"),
    )
    graph_application_mailbox: str = Field(
        default="",
        validation_alias=AliasChoices("GRAPH_APPLICATION_MAILBOX", "graph_application_mailbox"),
        description="Default mailbox UPN or object id for application mode when X-Graph-Mailbox is absent.",
    )
    graph_application_credential: Literal["client_secret", "managed_identity"] = Field(
        default="client_secret",
        validation_alias=AliasChoices("GRAPH_APPLICATION_CREDENTIAL", "graph_application_credential"),
        description="How application mode obtains its Graph token: client_secret (MSAL) or managed_identity.",
    )
    azure_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_CLIENT_ID", "azure_client_id"),
        description="Client id of the user-assigned managed identity (managed_identity credential).",
    )
    attachment_storage: Literal["", "azure_blob"] = Field(
        default="",
        validation_alias=AliasChoices("ATTACHMENT_STORAGE", "attachment_storage"),
        description="Remote attachment storage backend for save_attachment_to_storage; empty = disabled.",
    )
    attachment_blob_container_url: str = Field(
        default="",
        validation_alias=AliasChoices("ATTACHMENT_BLOB_CONTAINER_URL", "attachment_blob_container_url"),
        description="https://<account>.blob.core.windows.net/<container> (managed identity needs write access).",
    )
    attachment_allowed_prefixes: str = Field(
        default="",
        validation_alias=AliasChoices("ATTACHMENT_ALLOWED_PREFIXES", "attachment_allowed_prefixes"),
        description="Comma-separated key prefixes save_attachment_to_storage may write under; empty = any.",
    )
    graph_trust_request_headers: bool = Field(
        default=True,
        validation_alias=AliasChoices("GRAPH_TRUST_REQUEST_HEADERS", "graph_trust_request_headers"),
        description=(
            "If false, X-Graph-Token, X-OAuth-Session, X-Graph-Auth-Mode and X-Graph-Client-Secret "
            "are ignored (use behind a gateway). X-Graph-Mailbox is still honoured."
        ),
    )
    graph_allowed_mailboxes: str = Field(
        default="",
        validation_alias=AliasChoices("GRAPH_ALLOWED_MAILBOXES", "graph_allowed_mailboxes"),
        description="Comma-separated mailboxes application mode may access (case-insensitive); empty = no restriction.",
    )
    log_level: str = Field(
        default="",
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
        description=(
            "Log level for the root and outlook_mcp loggers (DEBUG, INFO, WARNING, ERROR, CRITICAL). "
            "Empty = leave logging unchanged."
        ),
    )
    graph_allow_client_secret_header: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "GRAPH_ALLOW_CLIENT_SECRET_HEADER",
            "graph_allow_client_secret_header",
        ),
        description="If true, X-Graph-Client-Secret may override client secret (dev only).",
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

    max_attachment_upload_bytes: int = Field(
        default=150 * 1024 * 1024,
        ge=1,
        validation_alias=AliasChoices("MAX_ATTACHMENT_UPLOAD_BYTES", "max_attachment_upload_bytes"),
        description="Reject any single outgoing attachment larger than this (Graph's practical ceiling is ~150MB).",
    )
    max_attachment_count: int = Field(
        default=10,
        ge=1,
        le=50,
        validation_alias=AliasChoices("MAX_ATTACHMENT_COUNT", "max_attachment_count"),
        description="Max number of attachments accepted per send_email/create_draft/create_reply_draft call.",
    )
    max_multimodal_attachment_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1,
        validation_alias=AliasChoices("MAX_MULTIMODAL_ATTACHMENT_BYTES", "max_multimodal_attachment_bytes"),
        description=(
            "Max decoded byte size get_attachment_content will inline as an ImageContent/EmbeddedResource "
            "block (base64 inflates ~33%, and this also becomes LLM context). Larger attachments get a "
            "metadata-only JSON response instead of the blob."
        ),
    )

    attachment_text_max_bytes: int = Field(
        default=15_000_000,
        ge=1,
        validation_alias=AliasChoices("ATTACHMENT_TEXT_MAX_BYTES", "attachment_text_max_bytes"),
        description="Max attachment size (PDF or text) get_attachment_text will download.",
    )

    attachment_text_max_pages: int = Field(
        default=200,
        ge=1,
        validation_alias=AliasChoices("ATTACHMENT_TEXT_MAX_PAGES", "attachment_text_max_pages"),
        description="Max PDF pages get_attachment_text extracts; beyond it the result is truncated.",
    )
    attachment_text_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices("ATTACHMENT_TEXT_TIMEOUT_SECONDS", "attachment_text_timeout_seconds"),
        description="Wall-clock bound for get_attachment_text extraction; on timeout the result is `unreadable`.",
    )

    classification_categories: str = Field(
        default=(
            "PAYMENT_REMINDER_SENT,INVOICE_NOT_RECEIVED,INVOICE_DISPUTE,PAYMENT_PROMISE,"
            "PAYMENT_CONFIRMATION,EXTENSION_REQUEST,PARTIAL_PAYMENT_NOTE,ESCALATION_LEGAL,"
            "INTERNAL_NOTE,UNCLASSIFIED,REMITTANCE_ADVICE,BALANCE_INQUIRY,"
            "CREDIT_NOTE_REQUEST,AUTO_REPLY,BILLING_UPDATE,AGREEMENT_REACHED,AGREEMENT_SIGNED"
        ),
        validation_alias=AliasChoices("CLASSIFICATION_CATEGORIES", "classification_categories"),
        description=(
            "Comma-separated classification taxonomy labels for categorize_email / apply_llm_category_to_email. "
            "UNCLASSIFIED is always included."
        ),
    )

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        s = (v or "").strip().upper()
        if s == "WARN":
            s = "WARNING"
        if s not in ("", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            msg = "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"
            raise ValueError(msg)
        return s

    @field_validator("graph_auth_mode")
    @classmethod
    def _normalize_graph_auth_mode(cls, v: str) -> str:
        s = (v or "delegated").lower().strip()
        if s not in ("delegated", "application"):
            return "delegated"
        return s

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

    def classification_category_set(self) -> frozenset[str]:
        """Parse ``classification_categories`` and ensure UNCLASSIFIED is always allowed."""
        cats = {c.strip() for c in self.classification_categories.split(",") if c.strip()}
        cats.add("UNCLASSIFIED")
        return frozenset(cats)


def parse_tool_names(raw: str) -> frozenset[str]:
    return frozenset(n.strip() for n in raw.split(",") if n.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


# MSAL rejects these outright (``_decorate_scope``) and then adds them itself, so passing one
# through is a hard ValueError while dropping it costs nothing — the refresh token still comes
# back because MSAL unions the reserved set into every delegated request.
_MSAL_RESERVED_SCOPES = frozenset({"openid", "profile", "offline_access"})


def oauth_scope_list(settings: Settings) -> list[str]:
    """Space-separated scopes from settings, plus Mail.Send and Mail.ReadWrite when writes are enabled.

    Reserved OIDC scopes are stripped: MSAL supplies them and raises if a caller passes any.
    """
    parts = [
        p
        for p in settings.graph_oauth_scopes.replace(",", " ").split()
        if p and p.lower() not in _MSAL_RESERVED_SCOPES
    ]
    if settings.enable_write_operations:
        if "Mail.Send" not in parts:
            parts.append("Mail.Send")
        if "Mail.ReadWrite" not in parts:
            parts.append("Mail.ReadWrite")
    return parts if parts else ["Mail.Read"]
