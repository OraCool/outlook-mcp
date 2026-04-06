"""Structured error payloads (ADR-006 token contract)."""

TOKEN_EXPIRED_PAYLOAD: dict[str, str | int] = {
    "error": "token_expired",
    "code": "ERR_GRAPH_TOKEN_EXPIRED",
    "message": "Entra access token expired. Obtain a fresh token and retry.",
    "retry_after_ms": 0,
}

MISSING_TOKEN_PAYLOAD: dict[str, str] = {
    "error": "missing_token",
    "code": "ERR_GRAPH_TOKEN_MISSING",
    "message": (
        "No Graph token: use X-Graph-Token, X-OAuth-Session (after /oauth/login), "
        "GRAPH_OAUTH_TOKEN_CACHE_PATH (device login), or GRAPH_DEV_TOKEN."
    ),
}
