"""Runtime configuration from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
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

    graph_dev_token: str | None = Field(default=None, validation_alias=AliasChoices("GRAPH_DEV_TOKEN"))
    azure_tenant_id: str | None = Field(default=None, validation_alias=AliasChoices("AZURE_TENANT_ID"))
    azure_client_id: str | None = Field(default=None, validation_alias=AliasChoices("AZURE_CLIENT_ID"))
    azure_client_secret: str | None = Field(default=None, validation_alias=AliasChoices("AZURE_CLIENT_SECRET"))

    enable_write_operations: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENABLE_WRITE_OPERATIONS", "enable_write_operations"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
