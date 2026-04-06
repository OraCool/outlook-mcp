"""Environment-driven settings for the MCP tester."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class OutlookAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = Field(
        ...,
        validation_alias=AliasChoices("LLM_PROVIDER", "llm_provider"),
        description="openai or anthropic",
    )

    openai_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    openai_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "openai_model"),
    )

    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        validation_alias=AliasChoices("ANTHROPIC_MODEL", "anthropic_model"),
    )

    mcp_transport: str = Field(
        default="streamable_http",
        validation_alias=AliasChoices("MCP_TRANSPORT", "mcp_transport"),
        description="streamable_http or stdio",
    )

    mcp_url: str = Field(
        default="http://127.0.0.1:8000/mcp",
        validation_alias=AliasChoices("MCP_URL", "mcp_url"),
    )

    x_graph_token: SecretStr | None = Field(default=None, validation_alias=AliasChoices("X_GRAPH_TOKEN"))

    mcp_stdio_command: str = Field(
        default="outlook-mcp-server",
        validation_alias=AliasChoices("MCP_STDIO_COMMAND", "mcp_stdio_command"),
    )


@lru_cache
def get_settings() -> OutlookAgentSettings:
    return OutlookAgentSettings()
