"""Shared helpers for tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from outlook_mcp.auth.graph_client import GraphMailClient
from outlook_mcp.auth.token_handler import (
    GraphTokenExpiredError,
    GraphTokenMissingError,
    resolve_delegated_graph_access_token,
)
from outlook_mcp.models.email import EmailAddress, EmailMessage
from outlook_mcp.models.errors import MISSING_TOKEN_PAYLOAD, TOKEN_EXPIRED_PAYLOAD

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


def graph_message_to_model(raw: dict[str, Any]) -> EmailMessage:
    def addr(blob: dict[str, Any] | None) -> EmailAddress | None:
        if not blob:
            return None
        ea = blob.get("emailAddress") or blob
        if not isinstance(ea, dict):
            return None
        return EmailAddress(address=ea.get("address"), name=ea.get("name"))

    body = raw.get("body") or {}
    to_list: list[EmailAddress] = []
    for r in raw.get("toRecipients") or []:
        a = addr(r)
        if a:
            to_list.append(a)

    return EmailMessage(
        id=raw["id"],
        subject=raw.get("subject"),
        body_preview=raw.get("bodyPreview"),
        body_content=body.get("content"),
        body_content_type=body.get("contentType"),
        received_date_time=raw.get("receivedDateTime"),
        sent_date_time=raw.get("sentDateTime"),
        conversation_id=raw.get("conversationId"),
        internet_message_id=raw.get("internetMessageId"),
        **{"from": addr(raw.get("from"))},
        sender=addr(raw.get("sender")),
        to_recipients=to_list,
        is_read=raw.get("isRead"),
        has_attachments=raw.get("hasAttachments"),
        categories=list(raw.get("categories") or []),
    )


def make_graph_client(ctx: Context | None) -> GraphMailClient:
    from outlook_mcp.config import get_settings

    token, _ = resolve_delegated_graph_access_token(ctx)
    timeout = float(get_settings().graph_http_timeout_seconds)
    return GraphMailClient(token, http_timeout=timeout)


def tool_error_token(e: Exception) -> dict[str, Any]:
    if isinstance(e, GraphTokenExpiredError):
        return dict(TOKEN_EXPIRED_PAYLOAD)
    if isinstance(e, GraphTokenMissingError):
        return dict(MISSING_TOKEN_PAYLOAD)
    return {"error": "graph_error", "message": str(e)}


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw model text (plain JSON or fenced code block)."""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()

    try:
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object")
        return parsed
    except Exception:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")

    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as err:
        raise ValueError(f"No valid JSON object found in model response: {err}") from err
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed
