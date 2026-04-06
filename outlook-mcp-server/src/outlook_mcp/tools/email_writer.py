"""Optional write operations (feature-flagged; ADR-005 prefers Graph API Bridge for send)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.config import get_settings
from outlook_mcp.tools._common import make_graph_client, tool_error_token
from outlook_mcp.tools._notify import tool_log_info, tool_log_warning, tool_report_progress

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
        await tool_log_info(ctx, "send_email: write_disabled (ENABLE_WRITE_OPERATIONS=false)")
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable send_email (see ADR-005/006).",
            }
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"send_email: start recipients={len(to_addresses)}")
    await tool_report_progress(ctx, 20, 100, message="send_email: start")
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": content_type, "content": body_text},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to_addresses],
        },
        "saveToSentItems": save_to_sent_items,
    }
    try:
        await tool_report_progress(ctx, 60, 100, message="send_email: calling Graph sendMail")
        await client.send_mail(payload)
        await tool_report_progress(ctx, 100, 100, message="send_email: complete")
        await tool_log_info(ctx, "send_email: Graph accepted message")
        return json.dumps({"ok": True, "message": "Message accepted by Graph sendMail."})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"send_email: http_error status={e.response.status_code}")
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
        await tool_log_info(ctx, "create_draft: write_disabled (ENABLE_WRITE_OPERATIONS=false)")
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable create_draft.",
            }
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, "create_draft: start")
    await tool_report_progress(ctx, 20, 100, message="create_draft: start")
    msg: dict = {
        "subject": subject,
        "body": {"contentType": content_type, "content": body_text},
    }
    if to_addresses:
        msg["toRecipients"] = [{"emailAddress": {"address": a}} for a in to_addresses]

    try:
        await tool_report_progress(ctx, 60, 100, message="create_draft: calling Graph")
        created = await client.create_message_draft(msg)
        await tool_report_progress(ctx, 100, 100, message="create_draft: complete")
        await tool_log_info(ctx, "create_draft: draft created")
        return json.dumps({"ok": True, "message": created}, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"create_draft: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": e.response.text[:2000],
            }
        )
