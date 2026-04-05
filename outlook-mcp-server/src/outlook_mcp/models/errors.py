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
    "message": "X-Graph-Token header was not provided and no dev/fallback credential is configured.",
}
