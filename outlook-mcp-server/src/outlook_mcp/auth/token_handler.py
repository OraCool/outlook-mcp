"""Resolve Microsoft Graph access tokens and mailbox context (delegated /me vs application /users/...)."""

from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING, Any

import jwt
import msal
from starlette.requests import Request

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

_BEARER_PREFIX = "bearer "

_cc_lock = threading.Lock()
_cc_token: str | None = None
_cc_exp: int = 0
_cc_cache_key: str | None = None


class GraphTokenExpiredError(Exception):
    """Raised when the Graph token is missing or JWT exp is in the past."""


class GraphTokenMissingError(Exception):
    """Raised when no token source is available."""


class GraphMailboxMissingError(Exception):
    """Raised when an application token is used but no mailbox was provided."""


def _header_token(request: Request | None, name: str) -> str | None:
    if request is None:
        return None
    raw = request.headers.get(name.lower()) or request.headers.get(name)
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith(_BEARER_PREFIX):
        raw = raw[7:].strip()
    return raw or None


def _mailbox_header(request: Request | None) -> str | None:
    if request is None:
        return None
    raw = request.headers.get("x-graph-mailbox") or request.headers.get("X-Graph-Mailbox")
    if not raw or not str(raw).strip():
        return None
    return str(raw).strip()


def _auth_mode_header(request: Request | None) -> str | None:
    if request is None:
        return None
    raw = request.headers.get("x-graph-auth-mode") or request.headers.get("X-Graph-Auth-Mode")
    if not raw or not str(raw).strip():
        return None
    return str(raw).strip()


def _exp_from_jwt(token: str) -> int | None:
    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False},
        )
        exp = decoded.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False},
        )
    except Exception:
        return {}


def _is_application_token(decoded: dict[str, Any], mode_header: str | None) -> bool:
    """Classify token as application (Graph /users/...) vs delegated (/me)."""
    if mode_header:
        m = mode_header.lower().strip()
        if m == "application":
            return True
        if m == "delegated":
            return False
    roles = decoded.get("roles")
    if isinstance(roles, list) and len(roles) > 0:
        return True
    scp = decoded.get("scp")
    if isinstance(scp, str) and scp.strip():
        return False
    return False


def _ensure_not_expired(token: str) -> None:
    exp = _exp_from_jwt(token)
    if exp is not None and exp <= int(time.time()):
        raise GraphTokenExpiredError("Graph token JWT exp claim is in the past")


def _resolve_mailbox(settings: Any, request: Request | None) -> str:
    mb = _mailbox_header(request)
    if mb:
        return mb
    env_mb = (getattr(settings, "graph_application_mailbox", None) or "").strip()
    if env_mb:
        return env_mb
    raise GraphMailboxMissingError(
        "Application Graph mode requires X-Graph-Mailbox header or GRAPH_APPLICATION_MAILBOX env var."
    )


def _token_from_msal_file_cache(settings: Any) -> tuple[str, int] | None:
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


def _tenant_for_application_flow(settings: Any) -> str:
    tid = (getattr(settings, "graph_tenant_id", None) or "").strip()
    if tid:
        return tid
    return (getattr(settings, "graph_oauth_tenant", None) or "").strip()


def _acquire_client_credentials_token(settings: Any, request: Request | None) -> tuple[str, int]:
    tenant = _tenant_for_application_flow(settings)
    client_id = (getattr(settings, "graph_application_client_id", None) or "").strip()
    sec_obj = getattr(settings, "graph_application_client_secret", None)
    secret = sec_obj.get_secret_value().strip() if sec_obj is not None else ""
    if getattr(settings, "graph_allow_client_secret_header", False) and request is not None:
        hdr = request.headers.get("x-graph-client-secret") or request.headers.get("X-Graph-Client-Secret")
        if hdr and str(hdr).strip():
            secret = str(hdr).strip()
    if not tenant or not client_id or not secret:
        raise GraphTokenMissingError(
            "client_credentials requires GRAPH_TENANT_ID (or GRAPH_OAUTH_TENANT), "
            "GRAPH_APPLICATION_CLIENT_ID, and GRAPH_APPLICATION_CLIENT_SECRET "
            "(or X-Graph-Client-Secret when GRAPH_ALLOW_CLIENT_SECRET_HEADER=true)."
        )
    cache_key = f"{tenant}:{client_id}"
    now = int(time.time())
    global _cc_token, _cc_exp, _cc_cache_key
    with _cc_lock:
        if (
            _cc_token
            and _cc_cache_key == cache_key
            and _cc_exp > now + 120
        ):
            return _cc_token, _cc_exp
    app = msal.ConfidentialClientApplication(
        client_id,
        client_credential=secret,
        authority=f"https://login.microsoftonline.com/{tenant}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if not result or "access_token" not in result:
        err = result.get("error_description") if isinstance(result, dict) else None
        oid = result.get("error") if isinstance(result, dict) else None
        msg = err or oid or "unknown_error"
        raise GraphTokenMissingError(f"client_credentials failed: {msg}")
    tok = result["access_token"]
    try:
        ttl = int(result.get("expires_in", 3599))
    except (TypeError, ValueError):
        ttl = 3599
    exp = now + max(60, ttl)
    with _cc_lock:
        _cc_token = tok
        _cc_exp = exp
        _cc_cache_key = cache_key
    return tok, exp


def _wants_client_credentials(settings: Any, mode_header: str | None) -> bool:
    if mode_header and mode_header.lower().strip() == "delegated":
        return False
    if mode_header and mode_header.lower().strip() == "application":
        return True
    return getattr(settings, "graph_auth_mode", "delegated") == "application"


def resolve_graph_access_token(ctx: Context | None) -> tuple[str, int, str | None]:
    """Return ``(access_token, expires_on_unix, mailbox_or_none)``.

    ``mailbox_or_none`` is ``None`` when using delegated ``/me``; otherwise the UPN or object ID
    for ``/users/{mailbox}/...``.
    """
    from outlook_mcp.config import get_settings

    request: Request | None = None
    if ctx is not None:
        try:
            rc = ctx.request_context
            request = rc.request  # type: ignore[assignment]
        except Exception:
            request = None

    settings = get_settings()
    mode_hdr = _auth_mode_header(request)

    def finish_bearer(token: str) -> tuple[str, int, str | None]:
        _ensure_not_expired(token)
        exp = _exp_from_jwt(token) or (int(time.time()) + 3600)
        decoded = _decode_jwt_payload(token)
        if _is_application_token(decoded, mode_hdr):
            mb = _resolve_mailbox(settings, request)
            return token, exp, mb
        return token, exp, None

    header_tok = _header_token(request, "x-graph-token")
    if header_tok:
        return finish_bearer(header_tok)

    oauth_hdr = _header_token(request, "x-oauth-session")
    if oauth_hdr and getattr(settings, "graph_oauth_enabled", False):
        from outlook_mcp.auth.oauth_session import get_oauth_session_store

        tok, exp = get_oauth_session_store().get_valid_access_token(oauth_hdr, settings)
        return tok, exp, None

    cached = _token_from_msal_file_cache(settings)
    if cached:
        tok, exp = cached
        return tok, exp, None

    if settings.graph_dev_token:
        dev = settings.graph_dev_token.get_secret_value().strip()
        if dev.lower().startswith(_BEARER_PREFIX):
            dev = dev[7:].strip()
        return finish_bearer(dev)

    if _wants_client_credentials(settings, mode_hdr):
        tok, exp = _acquire_client_credentials_token(settings, request)
        mb = _resolve_mailbox(settings, request)
        return tok, exp, mb

    raise GraphTokenMissingError(
        "No Graph token: set X-Graph-Token, X-OAuth-Session (after /oauth/login), "
        "GRAPH_OAUTH_TOKEN_CACHE_PATH (device login), GRAPH_DEV_TOKEN, or "
        "GRAPH_AUTH_MODE=application with GRAPH_APPLICATION_CLIENT_* and tenant env vars."
    )


def resolve_delegated_graph_access_token(ctx: Context | None) -> tuple[str, int]:
    """Return ``(access_token, expires_on_unix)`` for Graph calls.

    Prefer :func:`resolve_graph_access_token` when the caller needs mailbox context for
    application permissions (``/users/...``).
    """
    token, exp, _mb = resolve_graph_access_token(ctx)
    return token, exp
