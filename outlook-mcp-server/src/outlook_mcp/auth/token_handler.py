"""Resolve Microsoft Graph access tokens (delegated header, dev token, or client credentials)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import jwt
from starlette.requests import Request

from outlook_mcp.config import get_settings

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


class GraphTokenExpiredError(Exception):
    """Raised when the Graph token is missing or JWT exp is in the past."""


class GraphTokenMissingError(Exception):
    """Raised when no token source is available."""


def _header_token(request: Request | None, name: str) -> str | None:
    if request is None:
        return None
    # Starlette normalizes header names to lowercase
    raw = request.headers.get(name.lower()) or request.headers.get(name)
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw or None


def _exp_from_jwt(token: str) -> int | None:
    try:
        # Signature is verified by Microsoft Graph on each API call; we only read ``exp`` locally.
        decoded: dict[str, Any] = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False},
        )
        exp = decoded.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _ensure_not_expired(token: str) -> None:
    exp = _exp_from_jwt(token)
    if exp is not None and exp <= int(time.time()):
        raise GraphTokenExpiredError("Graph token JWT exp claim is in the past")


async def _client_credentials_token() -> tuple[str, int]:
    s = get_settings()
    if not (s.azure_tenant_id and s.azure_client_id and s.azure_client_secret):
        raise GraphTokenMissingError("Client credentials are not fully configured")

    from azure.identity.aio import ClientSecretCredential

    cred = ClientSecretCredential(
        s.azure_tenant_id,
        s.azure_client_id,
        s.azure_client_secret,
    )
    try:
        at = await cred.get_token("https://graph.microsoft.com/.default")
        return at.token, int(at.expires_on)
    finally:
        await cred.close()


async def resolve_graph_access_token(ctx: Context | None) -> tuple[str, int]:
    """Return (access_token, expires_on_unix).

    Order: HTTP ``X-Graph-Token`` → ``GRAPH_DEV_TOKEN`` → Azure client credentials.
    """
    request: Request | None = None
    if ctx is not None:
        try:
            rc = ctx.request_context
            request = rc.request  # type: ignore[assignment]
        except Exception:
            request = None

    header_tok = _header_token(request, "x-graph-token")
    if header_tok:
        _ensure_not_expired(header_tok)
        exp = _exp_from_jwt(header_tok) or (int(time.time()) + 3600)
        return header_tok, exp

    s = get_settings()
    if s.graph_dev_token:
        dev = s.graph_dev_token.strip()
        if dev.lower().startswith("bearer "):
            dev = dev[7:].strip()
        _ensure_not_expired(dev)
        exp = _exp_from_jwt(dev) or (int(time.time()) + 3600)
        return dev, exp

    return await _client_credentials_token()
