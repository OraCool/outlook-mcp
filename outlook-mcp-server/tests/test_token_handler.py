"""Token resolution and expiry checks."""

from __future__ import annotations

import time

import jwt
import pytest

from outlook_mcp.auth.token_handler import (
    GraphTokenExpiredError,
    GraphTokenMissingError,
    _ensure_not_expired,
    _exp_from_jwt,
    resolve_delegated_graph_access_token,
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


def test_resolve_delegated_token_from_graph_dev_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        graph_dev_token = "Bearer abc.def.ghi"

    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: _Settings())
    token, _ = resolve_delegated_graph_access_token(None)
    assert token == "abc.def.ghi"


def test_resolve_delegated_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        graph_dev_token = None

    monkeypatch.setattr("outlook_mcp.config.get_settings", lambda: _Settings())
    with pytest.raises(GraphTokenMissingError):
        resolve_delegated_graph_access_token(None)
