"""MSAL application factory for Entra ID (Graph delegated scopes)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import msal

if TYPE_CHECKING:
    from outlook_mcp.config import Settings


def oauth_authority_url(settings: "Settings") -> str:
    tenant = (settings.graph_oauth_tenant or "common").strip()
    return f"https://login.microsoftonline.com/{tenant}"


def build_msal_app(settings: "Settings", token_cache: msal.SerializableTokenCache | None = None) -> Any:
    """Confidential client if ``GRAPH_OAUTH_CLIENT_SECRET`` is set, else public (PKCE / device flow)."""
    authority = oauth_authority_url(settings)
    client_id = settings.graph_oauth_client_id.strip()
    if not client_id:
        msg = "GRAPH_OAUTH_CLIENT_ID is required for OAuth"
        raise ValueError(msg)
    secret = settings.graph_oauth_client_secret
    if secret is not None and secret.get_secret_value().strip():
        return msal.ConfidentialClientApplication(
            client_id,
            client_credential=secret.get_secret_value(),
            authority=authority,
            token_cache=token_cache,
        )
    return msal.PublicClientApplication(
        client_id,
        authority=authority,
        token_cache=token_cache,
    )
