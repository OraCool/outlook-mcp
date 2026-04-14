"""Token resolution and expiry checks."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt
import pytest
from pydantic import SecretStr

from outlook_mcp.auth.token_handler import (
    GraphMailboxMissingError,
    GraphTokenExpiredError,
    GraphTokenMissingError,
    _ensure_not_expired,
    _exp_from_jwt,
    resolve_delegated_graph_access_token,
    resolve_graph_access_token,
)


def test_exp_from_jwt_roundtrip() -> None:
    token = jwt.encode(
        {"exp": int(time.time()) + 3600, "sub": "user"},
        "x" * 32,
        algorithm="HS256",
    )
    exp = _exp_from_jwt(token if isinstance(token, str) else token.decode())
    assert exp is not None
    assert exp > int(time.time())


def test_ensure_not_expired_raises() -> None:
    token = jwt.encode(
        {"exp": int(time.time()) - 60, "sub": "user"},
        "x" * 32,
        algorithm="HS256",
    )
    tok = token if isinstance(token, str) else token.decode()
    with pytest.raises(GraphTokenExpiredError):
        _ensure_not_expired(tok)


def _base_settings(**kwargs: object) -> type:
    defaults: dict[str, object] = {
        "graph_dev_token": None,
        "graph_oauth_enabled": False,
        "graph_oauth_client_id": "",
        "graph_oauth_token_cache_path": None,
        "graph_auth_mode": "delegated",
        "graph_tenant_id": "",
        "graph_application_client_id": "",
        "graph_application_client_secret": None,
        "graph_application_mailbox": "",
        "graph_allow_client_secret_header": False,
        "graph_oauth_tenant": "common",
    }
    defaults.update(kwargs)

    class _Settings:
        pass

    for k, v in defaults.items():
        setattr(_Settings, k, v)
    return _Settings


def test_resolve_delegated_token_from_graph_dev_token(monkeypatch: pytest.MonkeyPatch) -> None:
    S = _base_settings(graph_dev_token=SecretStr("Bearer abc.def.ghi"))
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    token, _ = resolve_delegated_graph_access_token(None)
    assert token == "abc.def.ghi"


def test_resolve_delegated_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    S = _base_settings()
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    with pytest.raises(GraphTokenMissingError):
        resolve_delegated_graph_access_token(None)


def test_application_jwt_requires_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    tok = jwt.encode(
        {"exp": int(time.time()) + 3600, "roles": ["Mail.Read"]},
        "secret",
        algorithm="HS256",
    )
    S = _base_settings()
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())

    ctx = MagicMock()
    ctx.request_context.request.headers = {"x-graph-token": tok}

    with pytest.raises(GraphMailboxMissingError):
        resolve_graph_access_token(ctx)


def test_application_jwt_with_mailbox(monkeypatch: pytest.MonkeyPatch) -> None:
    tok = jwt.encode(
        {"exp": int(time.time()) + 3600, "roles": ["Mail.Read"]},
        "secret",
        algorithm="HS256",
    )
    S = _base_settings(graph_application_mailbox="shared@contoso.com")
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())

    ctx = MagicMock()
    ctx.request_context.request.headers = {"x-graph-token": tok}

    _t, _e, mb = resolve_graph_access_token(ctx)
    assert mb == "shared@contoso.com"


def test_client_credentials_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import outlook_mcp.auth.token_handler as th

    th._cc_token = None
    th._cc_exp = 0
    th._cc_cache_key = None

    S = _base_settings(
        graph_auth_mode="application",
        graph_tenant_id="tenant-id",
        graph_application_client_id="app-id",
        graph_application_client_secret=SecretStr("shh"),
        graph_application_mailbox="m@x.com",
    )
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())

    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {
        "access_token": "app-access",
        "expires_in": 3600,
    }
    monkeypatch.setattr("msal.ConfidentialClientApplication", lambda *a, **k: mock_app)

    t, _e, mb = resolve_graph_access_token(None)
    assert t == "app-access"
    assert mb == "m@x.com"
    mock_app.acquire_token_for_client.assert_called_once()
