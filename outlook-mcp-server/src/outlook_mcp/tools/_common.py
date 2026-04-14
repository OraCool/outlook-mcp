"""Shared helpers for tools."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from typing import TYPE_CHECKING, Any

from mcp.types import CreateMessageResultWithTools, TextContent

from outlook_mcp.auth.graph_client import GraphMailClient
from outlook_mcp.auth.token_handler import (
    GraphMailboxMissingError,
    GraphTokenExpiredError,
    GraphTokenMissingError,
    resolve_graph_access_token,
)
from outlook_mcp.models.email import EmailAddress, EmailMessage
from outlook_mcp.models.errors import (
    MISSING_MAILBOX_PAYLOAD,
    MISSING_TOKEN_PAYLOAD,
    TOKEN_EXPIRED_PAYLOAD,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


def graph_message_to_model(raw: dict[str, Any]) -> EmailMessage:
    """Map a Microsoft Graph ``/messages`` JSON object to ``EmailMessage``."""
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
    """Build a Graph client using token + mailbox context from ``ctx`` (or env fallbacks)."""
    from outlook_mcp.config import get_settings

    token, _exp, mailbox = resolve_graph_access_token(ctx)
    timeout = float(get_settings().graph_http_timeout_seconds)
    return GraphMailClient(token, http_timeout=timeout, mailbox=mailbox)


_EMAIL_LIKE_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)


def sanitize_client_error_message(message: str, max_len: int = 500) -> str:
    """Truncate and scrub likely PII from error text returned to clients or logs."""
    if not message:
        return message
    s = message.strip().replace("\n", " ").replace("\r", " ")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return _EMAIL_LIKE_RE.sub("[EMAIL_REDACTED]", s)


def minimize_email_response(email_json: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-deep copy of email JSON suitable for tool responses (no body_content)."""
    keys = (
        "id",
        "subject",
        "body_preview",
        "from",
        "sender",
        "to_recipients",
        "conversation_id",
        "received_date_time",
        "sent_date_time",
        "internet_message_id",
        "categories",
        "is_read",
        "has_attachments",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in email_json:
            out[k] = copy.deepcopy(email_json[k])
    bp = out.get("body_preview")
    if isinstance(bp, str) and len(bp) > 512:
        out["body_preview"] = bp[:509] + "..."
    subj = out.get("subject")
    if isinstance(subj, str) and len(subj) > 256:
        out["subject"] = subj[:253] + "..."
    return out


def email_json_for_tool_response(email_json: dict[str, Any], settings: Any) -> dict[str, Any]:
    """Full / minimal / redacted email payload for MCP tool JSON (see ``pii_response_level``)."""
    from outlook_mcp.pii.redactor import redact_email_json

    level = (getattr(settings, "pii_response_level", None) or "full").lower().strip()
    if level not in ("full", "minimal", "redacted"):
        level = "full"
    if level == "full":
        return copy.deepcopy(email_json)
    minimal = minimize_email_response(email_json)
    if level == "minimal":
        return minimal
    return redact_email_json(
        minimal,
        enabled=True,
        strategy=getattr(settings, "pii_redaction_strategy", "pseudonymize"),
        entities_csv=getattr(
            settings,
            "pii_entities",
            "EMAIL_ADDRESS,PERSON,PHONE_NUMBER,IBAN_CODE,CREDIT_CARD,IP_ADDRESS,LOCATION",
        ),
        deterministic_fallback=True,
    )


def tool_error_token(e: Exception) -> dict[str, Any]:
    """Stable JSON error payload for token problems or generic Graph failures."""
    if isinstance(e, GraphTokenExpiredError):
        return dict(TOKEN_EXPIRED_PAYLOAD)
    if isinstance(e, GraphTokenMissingError):
        return dict(MISSING_TOKEN_PAYLOAD)
    if isinstance(e, GraphMailboxMissingError):
        return dict(MISSING_MAILBOX_PAYLOAD)
    return {"error": "graph_error", "message": sanitize_client_error_message(str(e))}


_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


async def sampling_create_message(session: Any, *, timeout_seconds: float, **kwargs: Any) -> Any:
    """``session.create_message`` with a deadline so clients that never answer sampling cannot hang the server."""
    try:
        return await asyncio.wait_for(session.create_message(**kwargs), timeout=timeout_seconds)
    except TimeoutError as e:
        msg = (
            f"MCP sampling timed out after {timeout_seconds:.0f}s waiting for the client to answer "
            "sampling/createMessage. If you use MCP Inspector, complete or dismiss the sampling "
            "prompt in the UI, or use a client that handles sampling automatically (e.g. "
            "langgraph-mcp-tester with session_kwargs.sampling_callback)."
        )
        raise TimeoutError(msg) from e


def sampling_response_text(result: Any) -> str:
    """Collect assistant text from MCP sampling (single TextContent or list of blocks)."""
    content = getattr(result, "content", None)
    if content is None:
        return ""
    if isinstance(content, list):
        blocks = content
    elif isinstance(result, CreateMessageResultWithTools):
        blocks = result.content_as_list()
    else:
        blocks = [content]
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        else:
            text_attr = getattr(block, "text", None)
            if isinstance(text_attr, str):
                parts.append(text_attr)
    return "\n".join(parts)


def _strip_outer_fence(s: str) -> str:
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if len(lines) >= 3 and lines[-1].strip().startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return s


def _fenced_inners(s: str) -> list[str]:
    return [m.group(1).strip() for m in _FENCE_RE.finditer(s)]


def _balanced_object_end(s: str, start: int) -> int | None:
    """Index of closing ``}`` for a JSON object starting at ``start``, or None."""
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    i = start
    in_string = False
    escape = False
    while i < len(s):
        ch = s[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _object_slices(s: str) -> list[str]:
    out: list[str] = []
    pos = 0
    while True:
        j = s.find("{", pos)
        if j == -1:
            break
        end = _balanced_object_end(s, j)
        if end is not None:
            out.append(s[j : end + 1])
        pos = j + 1
    return out


_EMPTY_SAMPLING_RESPONSE = (
    "Empty model response from MCP sampling. When using MCP Inspector, paste a single JSON "
    "object as the assistant reply when completing sampling/createMessage."
)


def _safe_error_preview(raw: str, *, max_chars: int = 100) -> str | None:
    """Short, single-line snippet for parse errors — skip likely email echo or huge blobs."""
    if not raw or len(raw) > 280:
        return None
    if "BEGIN_UNTRUSTED_EMAIL_JSON" in raw or "END_UNTRUSTED_EMAIL_JSON" in raw:
        return None
    if "body_content" in raw:
        return None
    one_line = raw.replace("\n", " ").replace("\r", " ").strip()
    if len(one_line) > max_chars:
        one_line = one_line[: max_chars - 3].rstrip() + "..."
    return one_line


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw model text (plain JSON, fenced block, or embedded object)."""
    raw = text.strip()
    if not raw:
        raise ValueError(_EMPTY_SAMPLING_RESPONSE)
    candidate = _strip_outer_fence(raw)

    tried: list[str] = []
    seen: set[str] = set()

    def add_probe(p: str) -> None:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            tried.append(p)

    add_probe(candidate)
    for inner in _fenced_inners(raw):
        add_probe(inner)
    add_probe(raw)
    for sl in _object_slices(candidate):
        add_probe(sl)
    for sl in _object_slices(raw):
        add_probe(sl)

    last_err: json.JSONDecodeError | None = None
    for probe in tried:
        try:
            parsed = json.loads(probe)
        except json.JSONDecodeError as err:
            last_err = err
            continue
        if isinstance(parsed, dict):
            return parsed

    if "{" not in raw:
        msg = (
            "No JSON object found in model response (response contains no `{` character). "
            "When using MCP Inspector, paste one JSON object matching the system prompt."
        )
        prev = _safe_error_preview(raw)
        if prev:
            msg = f"{msg} Preview: {prev!r}"
        raise ValueError(msg)
    detail = str(last_err) if last_err else "response was not a JSON object"
    msg = f"No valid JSON object found in model response: {detail}"
    prev = _safe_error_preview(raw)
    if prev:
        msg = f"{msg} Preview: {prev!r}"
    err = ValueError(msg)
    raise err from last_err
