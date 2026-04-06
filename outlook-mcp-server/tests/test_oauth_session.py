"""OAuth session store and token resolution order."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from outlook_mcp.auth.oauth_session import (
    OAuthSessionStore,
    get_oauth_session_store,
    reset_oauth_session_store_for_tests,
)
from outlook_mcp.auth.token_handler import resolve_delegated_graph_access_token


@pytest.fixture
def oauth_settings() -> SimpleNamespace:
    return SimpleNamespace(
        graph_oauth_scopes="Mail.Read offline_access",
        enable_write_operations=False,
    )


def test_oauth_session_roundtrip(oauth_settings: SimpleNamespace) -> None:
    reset_oauth_session_store_for_tests()
    store = get_oauth_session_store()
    sid = store.create_session_from_msal_result(
        {"access_token": "access-xyz", "expires_in": 3600},
        oauth_settings,
    )
    tok, _exp = store.get_valid_access_token(sid, oauth_settings)
    assert tok == "access-xyz"


def test_oauth_session_refresh(monkeypatch: pytest.MonkeyPatch, oauth_settings: SimpleNamespace) -> None:
    reset_oauth_session_store_for_tests()
    store = OAuthSessionStore()
    sid = store.create_session_from_msal_result(
        {
            "access_token": "old",
            "refresh_token": "rt1",
            "expires_in": 1,
        },
        oauth_settings,
    )
    mock_app = MagicMock()
    mock_app.acquire_token_by_refresh_token.return_value = {
        "access_token": "new-access",
        "refresh_token": "rt2",
        "expires_in": 3600,
    }
    monkeypatch.setattr("outlook_mcp.auth.oauth_session.build_msal_app", lambda _s: mock_app)

    import time as real_time

    future_ts = real_time.time() + 900
    monkeypatch.setattr("outlook_mcp.auth.oauth_session.time.time", lambda: future_ts)

    tok, _ = store.get_valid_access_token(sid, oauth_settings)
    assert tok == "new-access"
    mock_app.acquire_token_by_refresh_token.assert_called_once()


def test_x_graph_token_precedence_over_oauth_session(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_oauth_session_store_for_tests()
    store = get_oauth_session_store()
    sid = store.create_session_from_msal_result(
        {"access_token": "from-oauth", "expires_in": 3600},
        SimpleNamespace(graph_oauth_scopes="Mail.Read offline_access", enable_write_operations=False),
    )

    class _S:
        graph_oauth_enabled = True
        graph_oauth_client_id = "cid"
        graph_oauth_token_cache_path = None
        graph_dev_token = None

    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: _S())

    ctx = MagicMock()
    req = MagicMock()
    req.headers = {"x-graph-token": "from-header", "x-oauth-session": sid}
    ctx.request_context.request = req

    token, _ = resolve_delegated_graph_access_token(ctx)
    assert token == "from-header"
