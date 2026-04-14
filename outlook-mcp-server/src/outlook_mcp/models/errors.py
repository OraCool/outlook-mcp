"""Structured error payloads for Graph token and mailbox resolution (tool JSON contract)."""

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
        "GRAPH_OAUTH_TOKEN_CACHE_PATH (device login), GRAPH_DEV_TOKEN, or "
        "GRAPH_AUTH_MODE=application with client credentials env vars."
    ),
}

MISSING_MAILBOX_PAYLOAD: dict[str, str] = {
    "error": "missing_mailbox",
    "code": "ERR_GRAPH_MAILBOX_MISSING",
    "message": (
        "Application Graph access requires a mailbox: set X-Graph-Mailbox (HTTP) or "
        "GRAPH_APPLICATION_MAILBOX (env)."
    ),
}
