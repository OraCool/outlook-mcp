"""Optional write operations (feature-flagged; ADR-005 prefers Graph API Bridge for send)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.config import get_settings
from outlook_mcp.tools._common import make_graph_client, tool_error_token

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


async def send_email(
    ctx: Context,
    subject: str,
    body_text: str,
    to_addresses: list[str],
    content_type: str = "Text",
    save_to_sent_items: bool = True,
) -> str:
    """Send an email from the signed-in user (delegated ``Mail.Send``). Disabled unless ENABLE_WRITE_OPERATIONS=true."""
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable send_email (see ADR-005/006).",
            }
        )

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": content_type, "content": body_text},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_addresses],
        },
        "saveToSentItems": save_to_sent_items,
    }
    try:
        client = await make_graph_client(ctx)
        await client.send_mail(payload)
        return json.dumps({"ok": True, "message": "Message accepted by Graph sendMail."})
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": e.response.text[:2000],
            }
        )


async def create_draft(
    ctx: Context,
    subject: str,
    body_text: str,
    to_addresses: list[str] | None = None,
    content_type: str = "Text",
) -> str:
    """Create a draft message in the signed-in user's Drafts folder."""
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable create_draft.",
            }
        )

    msg: dict = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body_text},
    }
    if to_addresses:
        msg["toRecipients"] = [{"emailAddress": {"address": a}} for a in to_addresses]

    try:
        client = await make_graph_client(ctx)
        created = await client.create_message_draft(msg)
        return json.dumps({"ok": True, "message": created}, indent=2)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": e.response.text[:2000],
            }
        )
