"""Token resolution and expiry checks."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt
import pytest
from pydantic import SecretStr

from outlook_mcp.auth.token_handler import (
    GraphConfigurationError,
    GraphMailboxMissingError,
    GraphMailboxNotAllowedError,
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


def _mi_settings(**kwargs: object) -> type:
    base: dict[str, object] = {
        "graph_auth_mode": "application",
        "graph_application_credential": "managed_identity",
        "azure_client_id": "cid",
        "graph_application_mailbox": "mailbox@contoso.com",
        "graph_trust_request_headers": True,
        "graph_allowed_mailboxes": "mailbox@contoso.com",
    }
    base.update(kwargs)
    return _base_settings(**base)


def _forbid_msal(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("MSAL must not be used")

    monkeypatch.setattr("msal.ConfidentialClientApplication", boom)
    monkeypatch.setattr("outlook_mcp.auth.token_handler._token_from_msal_file_cache", boom)


def test_application_mode_uses_managed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    S = _mi_settings(graph_dev_token=SecretStr("dev-token"))
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    _forbid_msal(monkeypatch)
    seen: dict[str, object] = {}

    def fake_mi(resource: str, *, client_id: str, **_: object) -> tuple[str, int]:
        seen.update(resource=resource, client_id=client_id)
        return "mi-token", 1234

    monkeypatch.setattr("outlook_mcp.auth.token_handler.get_managed_identity_token", fake_mi)
    assert resolve_graph_access_token(None) == ("mi-token", 1234, "mailbox@contoso.com")
    assert seen == {"resource": "https://graph.microsoft.com", "client_id": "cid"}


def test_untrusted_headers_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    S = _mi_settings(
        graph_trust_request_headers=False,
        graph_allow_client_secret_header=True,
        graph_oauth_enabled=True,
        graph_allowed_mailboxes="hdr@contoso.com",
    )
    from outlook_mcp.auth import oauth_session

    def no_session(*a: object, **k: object) -> None:
        raise AssertionError("OAuth session store must not be consulted")

    monkeypatch.setattr(oauth_session, "get_oauth_session_store", no_session)
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    _forbid_msal(monkeypatch)
    monkeypatch.setattr(
        "outlook_mcp.auth.token_handler.get_managed_identity_token",
        lambda resource, *, client_id, **_: ("mi-token", 1234),
    )
    ctx = MagicMock()
    ctx.request_context.request.headers = {
        "x-graph-token": "other",
        "x-oauth-session": "s",
        "x-graph-auth-mode": "delegated",
        "x-graph-client-secret": "x",
        "x-graph-mailbox": "hdr@contoso.com",
    }
    assert resolve_graph_access_token(ctx) == ("mi-token", 1234, "hdr@contoso.com")


def test_mailbox_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    S = _mi_settings(graph_allowed_mailboxes="a@contoso.com,B@contoso.com")
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    monkeypatch.setattr(
        "outlook_mcp.auth.token_handler.get_managed_identity_token",
        lambda resource, *, client_id, **_: ("mi-token", 1234),
    )
    ctx = MagicMock()
    ctx.request_context.request.headers = {"x-graph-mailbox": "b@contoso.com"}
    assert resolve_graph_access_token(ctx)[2] == "b@contoso.com"

    ctx.request_context.request.headers = {"x-graph-mailbox": "c@contoso.com"}
    with pytest.raises(GraphMailboxNotAllowedError) as ei:
        resolve_graph_access_token(ctx)
    assert "contoso.com" not in str(ei.value)

    # default mailbox from env is checked too
    ctx.request_context.request.headers = {}
    with pytest.raises(GraphMailboxNotAllowedError):
        resolve_graph_access_token(ctx)


def test_untrusted_headers_client_secret_uses_env_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    import outlook_mcp.auth.token_handler as th

    th._cc_token = None
    th._cc_exp = 0
    th._cc_cache_key = None
    S = _base_settings(
        graph_auth_mode="application",
        graph_tenant_id="tenant-id",
        graph_application_client_id="app-id",
        graph_application_client_secret=SecretStr("env-secret"),
        graph_application_mailbox="m@contoso.com",
        graph_allow_client_secret_header=True,
        graph_trust_request_headers=False,
    )
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    seen: dict[str, object] = {}
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {"access_token": "app-access", "expires_in": 3600}

    def fake_cca(client_id: str, client_credential: str, **k: object) -> MagicMock:
        seen["secret"] = client_credential
        return mock_app

    monkeypatch.setattr("msal.ConfidentialClientApplication", fake_cca)
    ctx = MagicMock()
    ctx.request_context.request.headers = {"x-graph-client-secret": "header-secret"}
    t, _e, _mb = resolve_graph_access_token(ctx)
    assert t == "app-access"
    assert seen["secret"] == "env-secret"


@pytest.mark.parametrize("trust_headers", [True, False])
@pytest.mark.parametrize("allowlist", ["", "   "])
def test_managed_identity_requires_allowlist(monkeypatch: pytest.MonkeyPatch, trust_headers: bool, allowlist: str) -> None:
    S = _mi_settings(graph_trust_request_headers=trust_headers, graph_allowed_mailboxes=allowlist)
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    with pytest.raises(GraphConfigurationError, match="GRAPH_ALLOWED_MAILBOXES"):
        resolve_graph_access_token(None)


def test_client_secret_without_allowlist_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Documented multi-mailbox use of client_secret application mode is unchanged.
    import outlook_mcp.auth.token_handler as th

    th._cc_token = None
    th._cc_exp = 0
    th._cc_cache_key = None
    S = _base_settings(
        graph_auth_mode="application",
        graph_application_credential="client_secret",
        graph_tenant_id="tenant-id",
        graph_application_client_id="app-id",
        graph_application_client_secret=SecretStr("shh"),
        graph_application_mailbox="m@x.com",
        graph_allowed_mailboxes="",
    )
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {"access_token": "app-access", "expires_in": 3600}
    monkeypatch.setattr("msal.ConfidentialClientApplication", lambda *a, **k: mock_app)
    t, _e, mb = resolve_graph_access_token(None)
    assert t == "app-access"
    assert mb == "m@x.com"


def test_managed_identity_requires_application_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    S = _mi_settings(graph_auth_mode="delegated")
    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: S())
    with pytest.raises(GraphConfigurationError, match="GRAPH_AUTH_MODE"):
        resolve_graph_access_token(None)
