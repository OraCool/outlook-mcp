"""Device-code OAuth CLI: acquire Graph delegated token and persist MSAL cache for stdio/silent refresh."""

from __future__ import annotations

import os
import sys
from typing import Any


def _default_cache_path() -> str:
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = xdg if xdg else os.path.join(os.path.expanduser("~"), ".cache")
    directory = os.path.join(base, "outlook-mcp")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    return os.path.join(directory, "msal_token_cache.json")


def main() -> None:
    import msal

    from outlook_mcp.auth.oauth_msal import build_msal_app
    from outlook_mcp.config import get_settings, oauth_scope_list

    s = get_settings()
    if not s.graph_oauth_client_id.strip():
        print("Set GRAPH_OAUTH_CLIENT_ID (and GRAPH_OAUTH_TENANT if needed) in the environment.", file=sys.stderr)
        raise SystemExit(1)

    path = (s.graph_oauth_token_cache_path or "").strip() or _default_cache_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)

    cache = msal.SerializableTokenCache()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                blob = f.read()
            if blob:
                cache.deserialize(blob)
        except OSError as e:
            print(f"Could not read cache {path}: {e}", file=sys.stderr)
            raise SystemExit(1) from e

    try:
        app = build_msal_app(s, token_cache=cache)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1) from e

    scopes = oauth_scope_list(s)
    accounts = app.get_accounts()
    if accounts:
        silent = app.acquire_token_silent(scopes, account=accounts[0])
        if silent and "access_token" in silent:
            print("Existing cache already has a valid token; refreshing silently succeeded.")
            _write_cache(path, cache)
            print(f"Cache: {path}")
            print(f"Set GRAPH_OAUTH_TOKEN_CACHE_PATH={path} for the MCP server (stdio or HTTP).")
            return

    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        print(f"Failed to start device flow: {flow.get('error')}", file=sys.stderr)
        raise SystemExit(1)

    print(flow["message"], file=sys.stderr)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or result
        print(f"Device login failed: {err}", file=sys.stderr)
        raise SystemExit(1)

    _write_cache(path, cache)
    print(f"Signed in. MSAL cache written to: {path}", file=sys.stderr)
    print(f"Set GRAPH_OAUTH_TOKEN_CACHE_PATH={path} when running outlook-mcp-server.", file=sys.stderr)


def _write_cache(path: str, cache: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cache.serialize())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as e:
        print(f"Could not write cache {path}: {e}", file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
