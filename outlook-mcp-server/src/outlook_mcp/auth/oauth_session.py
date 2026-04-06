"""In-memory OAuth auth-code flow state and MCP session tokens (single-process only)."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from outlook_mcp.auth.oauth_msal import build_msal_app
from outlook_mcp.config import Settings, oauth_scope_list


@dataclass
class _PendingFlow:
    flow: dict[str, Any]
    created_at: float


@dataclass
class _SessionRecord:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scopes: list[str]


_FLOW_TTL_S = 900.0
_store_lock = threading.Lock()
_store: OAuthSessionStore | None = None


class OAuthSessionStore:
    """Thread-safe pending auth-code flows and post-login MCP sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending_by_state: dict[str, _PendingFlow] = {}
        self._sessions: dict[str, _SessionRecord] = {}

    def _prune_flows_unlocked(self) -> None:
        now = time.time()
        dead = [k for k, v in self._pending_by_state.items() if now - v.created_at > _FLOW_TTL_S]
        for k in dead:
            del self._pending_by_state[k]

    def start_auth_code_flow(self, settings: Settings) -> dict[str, Any]:
        """Return MSAL flow dict; caller redirects user to flow[\"auth_uri\"]. Stores flow by state."""
        scopes = oauth_scope_list(settings)
        app = build_msal_app(settings)
        flow = app.initiate_auth_code_flow(
            scopes,
            redirect_uri=settings.graph_oauth_redirect_uri.strip() or None,
        )
        state = flow.get("state")
        if not state or not isinstance(state, str):
            msg = "MSAL flow missing state"
            raise RuntimeError(msg)
        with self._lock:
            self._prune_flows_unlocked()
            self._pending_by_state[state] = _PendingFlow(flow=dict(flow), created_at=time.time())
        return flow

    def pop_flow(self, state: str) -> dict[str, Any] | None:
        with self._lock:
            self._prune_flows_unlocked()
            pending = self._pending_by_state.pop(state, None)
            return dict(pending.flow) if pending else None

    def complete_auth_code(self, settings: Settings, flow: dict[str, Any], auth_query: dict[str, str]) -> dict[str, Any]:
        """Exchange authorization code; returns MSAL result dict (tokens or error)."""
        app = build_msal_app(settings)
        # MSAL mutates flow (e.g. pop claims_challenge); use a copy for safety across retries.
        flow_copy = dict(flow)
        return app.acquire_token_by_auth_code_flow(flow_copy, auth_query, scopes=oauth_scope_list(settings))

    def create_session_from_msal_result(self, result: dict[str, Any], settings: Settings) -> str:
        """Persist tokens; returns opaque session id for ``X-OAuth-Session`` header."""
        access = result.get("access_token")
        if not access or not isinstance(access, str):
            msg = "MSAL result missing access_token"
            raise ValueError(msg)
        refresh = result.get("refresh_token")
        if refresh is not None and not isinstance(refresh, str):
            refresh = None
        expires_in = result.get("expires_in")
        try:
            ttl = int(expires_in) if expires_in is not None else 3600
        except (TypeError, ValueError):
            ttl = 3600
        expires_at = time.time() + max(60, ttl)
        scopes = oauth_scope_list(settings)
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[sid] = _SessionRecord(
                access_token=access,
                refresh_token=refresh,
                expires_at=expires_at,
                scopes=scopes,
            )
        return sid

    def get_valid_access_token(self, session_id: str, settings: Settings) -> tuple[str, int]:
        """Return (access_token, expires_on_unix). Refreshes with refresh_token when near expiry."""
        now = time.time()
        with self._lock:
            rec = self._sessions.get(session_id)
            if rec is None:
                from outlook_mcp.auth.token_handler import GraphTokenExpiredError

                raise GraphTokenExpiredError("Unknown or expired OAuth session; sign in again at /oauth/login.")
            # Refresh if expiring within 120s
            if now < rec.expires_at - 120:
                exp_int = int(rec.expires_at)
                return rec.access_token, exp_int

            refresh = rec.refresh_token
            scopes = rec.scopes

        if not refresh:
            with self._lock:
                self._sessions.pop(session_id, None)
            from outlook_mcp.auth.token_handler import GraphTokenExpiredError

            raise GraphTokenExpiredError("OAuth session expired and no refresh token; sign in again at /oauth/login.")

        app = build_msal_app(settings)
        result = app.acquire_token_by_refresh_token(refresh, scopes=scopes)
        if "access_token" not in result:
            with self._lock:
                self._sessions.pop(session_id, None)
            from outlook_mcp.auth.token_handler import GraphTokenExpiredError

            err = result.get("error_description") or result.get("error") or "token refresh failed"
            raise GraphTokenExpiredError(str(err))

        new_access = result["access_token"]
        new_refresh = result.get("refresh_token") or refresh
        try:
            ttl = int(result.get("expires_in", 3600))
        except (TypeError, ValueError):
            ttl = 3600
        new_expires = time.time() + max(60, ttl)
        with self._lock:
            self._sessions[session_id] = _SessionRecord(
                access_token=new_access,
                refresh_token=new_refresh if isinstance(new_refresh, str) else refresh,
                expires_at=new_expires,
                scopes=scopes,
            )
        return new_access, int(new_expires)


def get_oauth_session_store() -> OAuthSessionStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = OAuthSessionStore()
        return _store


def reset_oauth_session_store_for_tests() -> None:
    """Clear singleton (tests only)."""
    global _store
    with _store_lock:
        _store = None
