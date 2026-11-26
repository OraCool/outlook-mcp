"""Managed-identity token fetch/cache and its use in application mode."""

from __future__ import annotations

import httpx
import pytest

from outlook_mcp.auth.managed_identity import (
    ManagedIdentityError,
    clear_managed_identity_cache,
    get_managed_identity_token,
)

ENDPOINT = "http://127.0.0.1:42356/msi/token"


@pytest.fixture(autouse=True)
def _mi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("IDENTITY_HEADER", "hdr-value")
    clear_managed_identity_cache()
    yield
    clear_managed_identity_cache()


def _client(handler, calls: list[httpx.Request]) -> httpx.Client:
    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped))


def test_mi_token_fetch_and_cache() -> None:
    calls: list[httpx.Request] = []
    t0 = 1_000_000.0
    http = _client(
        lambda r: httpx.Response(200, json={"access_token": "t1", "expires_on": str(int(t0) + 3600)}),
        calls,
    )
    a = get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: t0)
    b = get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: t0 + 10)
    assert a == b == ("t1", int(t0) + 3600)
    assert len(calls) == 1
    req = calls[0]
    assert req.headers["X-IDENTITY-HEADER"] == "hdr-value"
    assert dict(req.url.params) == {
        "resource": "https://graph.microsoft.com",
        "client_id": "cid",
        "api-version": "2019-08-01",
    }


def test_mi_token_refresh_near_expiry() -> None:
    calls: list[httpx.Request] = []
    t0 = 1_000_000.0
    exp = int(t0) + 3600
    http = _client(lambda r: httpx.Response(200, json={"access_token": "t1", "expires_on": str(exp)}), calls)
    get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: t0)
    get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: exp - 301)
    assert len(calls) == 1
    get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: exp - 299)
    assert len(calls) == 2


def test_mi_cache_is_per_resource() -> None:
    calls: list[httpx.Request] = []
    http = _client(lambda r: httpx.Response(200, json={"access_token": "t", "expires_on": "9999999999"}), calls)
    get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: 1.0)
    get_managed_identity_token("https://storage.azure.com/", client_id="cid", http=http, now=lambda: 1.0)
    assert len(calls) == 2


def test_mi_error_has_no_token() -> None:
    http = _client(lambda r: httpx.Response(400, text="bad request secret-token"), [])
    with pytest.raises(ManagedIdentityError) as ei:
        get_managed_identity_token("https://graph.microsoft.com", client_id="cid", http=http, now=lambda: 1.0)
    assert "secret-token" not in str(ei.value)
    assert "400" in str(ei.value)


def test_mi_missing_endpoint_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IDENTITY_ENDPOINT")
    with pytest.raises(ManagedIdentityError):
        get_managed_identity_token("https://graph.microsoft.com", client_id="cid", now=lambda: 1.0)
