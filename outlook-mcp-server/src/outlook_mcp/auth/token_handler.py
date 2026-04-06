"""Resolve Microsoft Graph access tokens: per-request delegated token only."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import jwt
import msal
from starlette.requests import Request

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

_BEARER_PREFIX = "bearer "


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
    if raw.lower().startswith(_BEARER_PREFIX):
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


def _token_from_msal_file_cache(settings: Any) -> tuple[str, int] | None:
    """Silent token from ``GRAPH_OAUTH_TOKEN_CACHE_PATH`` (device-code / MSAL cache).

    Uses ``accounts[0]`` after ``get_accounts()`` only. One cache file shared by many
    tenants in a single process is unsupported: everyone would get the same account.
    """
    path = getattr(settings, "graph_oauth_token_cache_path", None)
    if not path or not str(path).strip():
        return None
    path = str(path).strip()
    if not os.path.isfile(path):
        return None
    client_id = getattr(settings, "graph_oauth_client_id", "") or ""
    if not str(client_id).strip():
        return None
    from outlook_mcp.auth.oauth_msal import build_msal_app
    from outlook_mcp.config import oauth_scope_list

    try:
        cache = msal.SerializableTokenCache()
        with open(path, encoding="utf-8") as f:
            blob = f.read()
        if blob:
            cache.deserialize(blob)
        app = build_msal_app(settings, token_cache=cache)
        accounts = app.get_accounts()
        if not accounts:
            return None
        scopes = oauth_scope_list(settings)
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if not result or "access_token" not in result:
            return None
        try:
            ttl = int(result.get("expires_in", 3600))
        except (TypeError, ValueError):
            ttl = 3600
        exp = int(time.time()) + max(60, ttl)
        return result["access_token"], exp
    except OSError:
        return None


def resolve_delegated_graph_access_token(ctx: Context | None) -> tuple[str, int]:
    """Return (access_token, expires_on_unix) for delegated Graph calls.

    Order:

    1. ``X-Graph-Token`` (Path C / ADR-006).
    2. ``X-OAuth-Session`` when ``GRAPH_OAUTH_ENABLED`` (browser login, in-memory session).
    3. MSAL cache file at ``GRAPH_OAUTH_TOKEN_CACHE_PATH`` (e.g. after ``outlook-mcp-oauth-device``).
    4. ``GRAPH_DEV_TOKEN`` (local dev only).
    """
    from outlook_mcp.config import get_settings

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

    oauth_hdr = _header_token(request, "x-oauth-session")
    if oauth_hdr and getattr(s, "graph_oauth_enabled", False):
        from outlook_mcp.auth.oauth_session import get_oauth_session_store

        tok, exp = get_oauth_session_store().get_valid_access_token(oauth_hdr, s)
        return tok, exp

    cached = _token_from_msal_file_cache(s)
    if cached:
        return cached

    if s.graph_dev_token:
        dev = s.graph_dev_token.get_secret_value().strip()
        if dev.lower().startswith(_BEARER_PREFIX):
            dev = dev[7:].strip()
        _ensure_not_expired(dev)
        exp = _exp_from_jwt(dev) or (int(time.time()) + 3600)
        return dev, exp

    raise GraphTokenMissingError(
        "No Graph token: set X-Graph-Token, X-OAuth-Session (after /oauth/login), "
        "GRAPH_OAUTH_TOKEN_CACHE_PATH (device login), or GRAPH_DEV_TOKEN."
    )
