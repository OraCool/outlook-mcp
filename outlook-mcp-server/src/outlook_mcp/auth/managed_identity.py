"""Azure managed-identity access tokens (App Service / Container Apps identity endpoint)."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

import httpx

_API_VERSION = "2019-08-01"
_REFRESH_MARGIN_SECONDS = 300

_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[str, int]] = {}


class ManagedIdentityError(Exception):
    """Managed-identity token request failed. The message never contains a token."""


def clear_managed_identity_cache() -> None:
    with _lock:
        _cache.clear()


def get_managed_identity_token(
    resource: str,
    *,
    client_id: str,
    http: httpx.Client | None = None,
    now: Callable[[], float] = time.time,
) -> tuple[str, int]:
    """Return ``(access_token, expires_on_unix)`` for ``resource``.

    Cached per (resource, client_id) until 300 s before ``expires_on``.
    """
    key = (resource, client_id)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now() < hit[1] - _REFRESH_MARGIN_SECONDS:
            return hit

    endpoint = os.environ.get("IDENTITY_ENDPOINT", "").strip()
    header = os.environ.get("IDENTITY_HEADER", "").strip()
    if not endpoint or not header:
        raise ManagedIdentityError(
            "Managed identity endpoint not available: IDENTITY_ENDPOINT / IDENTITY_HEADER are not set."
        )

    params = {"resource": resource, "api-version": _API_VERSION}
    if client_id:
        params["client_id"] = client_id

    own_client = http is None
    client = http or httpx.Client(timeout=10.0)
    try:
        try:
            resp = client.get(endpoint, params=params, headers={"X-IDENTITY-HEADER": header})
        except httpx.HTTPError as e:
            raise ManagedIdentityError(f"Managed identity token request failed: {type(e).__name__}") from None
    finally:
        if own_client:
            client.close()

    if resp.status_code != 200:
        raise ManagedIdentityError(f"Managed identity token request failed: HTTP {resp.status_code}")
    try:
        body = resp.json()
        token = str(body["access_token"])
        expires_on = int(body["expires_on"])
    except (ValueError, KeyError, TypeError):
        raise ManagedIdentityError(
            f"Managed identity token response (HTTP {resp.status_code}) was malformed"
        ) from None
    if not token:
        raise ManagedIdentityError("Managed identity token response contained no access_token")

    with _lock:
        _cache[key] = (token, expires_on)
    return token, expires_on
