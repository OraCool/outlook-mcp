"""Optional write operations (feature-flagged via ENABLE_WRITE_OPERATIONS).

Many deployments send outbound mail from a dedicated service; keep writes disabled
unless this process should call Graph send/category APIs directly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from outlook_mcp.auth.graph_client import MailFolderAmbiguousError, MailFolderNotFoundError
from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.config import get_settings
from outlook_mcp.tools._common import make_graph_client, sanitize_client_error_message, tool_error_token
from outlook_mcp.tools._notify import tool_log_info, tool_log_warning, tool_report_progress
from outlook_mcp.tools.mail_query_params import graph_importance_for_patch

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

_MAX_MESSAGE_CATEGORIES = 25


async def set_message_categories(ctx: Context, message_id: str, categories: list[str]) -> str:
    """Set Outlook message category tags (delegated ``Mail.ReadWrite``). Replaces the entire ``categories`` list.

    Disabled unless ENABLE_WRITE_OPERATIONS=true.
    """
    s = get_settings()
    if not s.enable_write_operations:
        await tool_log_info(ctx, "set_message_categories: write_disabled (ENABLE_WRITE_OPERATIONS=false)")
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable set_message_categories (requires Mail.ReadWrite).",
            }
        )

    if not categories:
        return json.dumps({"error": "validation_error", "message": "categories must be a non-empty list."})
    if len(categories) > _MAX_MESSAGE_CATEGORIES:
        return json.dumps(
            {
                "error": "validation_error",
                "message": f"At most {_MAX_MESSAGE_CATEGORIES} categories allowed per message.",
            }
        )
    for c in categories:
        if not isinstance(c, str) or not c.strip():
            return json.dumps(
                {"error": "validation_error", "message": "Each category must be a non-empty string."}
            )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    trimmed = [c.strip() for c in categories]
    await tool_log_info(ctx, f"set_message_categories: start message_id={message_id!r} count={len(trimmed)}")
    await tool_report_progress(ctx, 20, 100, message="set_message_categories: start")
    try:
        await tool_report_progress(ctx, 60, 100, message="set_message_categories: calling Graph")
        await client.update_message(message_id, {"categories": trimmed})
        await tool_report_progress(ctx, 100, 100, message="set_message_categories: complete")
        await tool_log_info(ctx, "set_message_categories: Graph PATCH ok")
        return json.dumps({"ok": True, "message_id": message_id, "categories": trimmed})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"set_message_categories: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"set_message_categories: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


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
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable send_email.",
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
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"send_email: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def send_draft_email(ctx: Context, draft_id: str) -> str:
    """Send an existing draft email by Graph message id (delegated ``Mail.Send``)."""
    s = get_settings()
    if not s.enable_write_operations:
        await tool_log_info(ctx, "send_draft_email: write_disabled (ENABLE_WRITE_OPERATIONS=false)")
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable send_draft_email.",
            }
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"send_draft_email: start draft_id={draft_id!r}")
    await tool_report_progress(ctx, 20, 100, message="send_draft_email: start")
    try:
        await tool_report_progress(ctx, 60, 100, message="send_draft_email: calling Graph messages/{id}/send")
        await client.send_draft(draft_id)
        await tool_report_progress(ctx, 100, 100, message="send_draft_email: complete")
        await tool_log_info(ctx, "send_draft_email: Graph accepted draft send")
        return json.dumps({"ok": True, "draft_id": draft_id, "message": "Draft accepted by Graph send endpoint."})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"send_draft_email: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"send_draft_email: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


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
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"create_draft: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def mark_as_read(ctx: Context, message_id: str, is_read: bool = True) -> str:
    """Mark a message as read (or unread). Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite."""
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {"error": "write_disabled", "message": "Set ENABLE_WRITE_OPERATIONS=true to enable mark_as_read."}
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"mark_as_read: message_id={message_id!r} is_read={is_read}")
    try:
        await client.update_message(message_id, {"isRead": is_read})
        return json.dumps({"ok": True, "message_id": message_id, "is_read": is_read})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"mark_as_read: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"mark_as_read: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def set_email_priority(ctx: Context, message_id: str, priority: str) -> str:
    """Set Outlook message importance (Graph ``importance``). Requires ENABLE_WRITE_OPERATIONS and Mail.ReadWrite.

    ``priority``: ``HIGH``, ``MEDIUM``, or ``LOW`` (maps to Graph ``high``, ``normal``, ``low``).
    Persists on the message; not the same as classifier ``priority`` on ``categorize_email``.
    """
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable set_email_priority (requires Mail.ReadWrite).",
            }
        )

    try:
        importance = graph_importance_for_patch(priority)
    except ValueError as e:
        return json.dumps({"error": "validation_error", "message": str(e)})

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"set_email_priority: message_id={message_id!r} importance={importance!r}")
    await tool_report_progress(ctx, 20, 100, message="set_email_priority: start")
    try:
        await tool_report_progress(ctx, 60, 100, message="set_email_priority: calling Graph")
        await client.update_message(message_id, {"importance": importance})
        await tool_report_progress(ctx, 100, 100, message="set_email_priority: complete")
        return json.dumps({"ok": True, "message_id": message_id, "importance": importance})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"set_email_priority: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"set_email_priority: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def move_email(ctx: Context, message_id: str, destination_folder_id: str) -> str:
    """Move a message to a different mail folder. Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite.

    Use ``list_folders`` to discover folder IDs.
    """
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {"error": "write_disabled", "message": "Set ENABLE_WRITE_OPERATIONS=true to enable move_email."}
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"move_email: message_id={message_id!r} dest={destination_folder_id!r}")
    try:
        moved = await client.move_message(message_id, destination_folder_id)
        return json.dumps({"ok": True, "message": moved}, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"move_email: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"move_email: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def create_mail_folder(
    ctx: Context,
    display_name: str,
    parent_folder_id: str | None = None,
    parent_folder_name: str | None = None,
) -> str:
    """Create a mail folder at the mailbox root, or a subfolder under a parent.

    Parent may be given as ``parent_folder_id`` (Graph id or well-known name) or
    ``parent_folder_name`` (resolved case-insensitively; same semantics as ``list_inbox``).
    Do not set both parent fields.

    Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite. Use ``list_folders`` for ids.
    """
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable create_mail_folder (requires Mail.ReadWrite).",
            }
        )

    if not isinstance(display_name, str) or not display_name.strip():
        return json.dumps({"error": "validation_error", "message": "display_name must be a non-empty string."})

    if parent_folder_id and parent_folder_name:
        return json.dumps(
            {
                "error": "invalid_parameters",
                "message": "Specify only one of parent_folder_id or parent_folder_name.",
            }
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    effective_parent_id = parent_folder_id
    if parent_folder_name is not None:
        pn = parent_folder_name.strip()
        if not pn:
            return json.dumps(
                {
                    "error": "validation_error",
                    "message": "parent_folder_name must be non-empty when set.",
                }
            )
        try:
            effective_parent_id = await client.resolve_mail_folder_id_by_display_name(pn)
        except MailFolderNotFoundError as e:
            return json.dumps(
                {
                    "error": "folder_not_found",
                    "message": str(e),
                    "folder_name": e.display_name,
                }
            )
        except MailFolderAmbiguousError as e:
            return json.dumps(
                {
                    "error": "folder_ambiguous",
                    "message": str(e),
                    "folder_name": e.display_name,
                    "match_count": e.match_count,
                }
            )

    await tool_log_info(
        ctx,
        f"create_mail_folder: display_name={display_name!r} parent_folder_id={effective_parent_id!r}",
    )
    try:
        created = await client.create_mail_folder(
            display_name.strip(), parent_folder_id=effective_parent_id
        )
        payload: dict[str, object] = {"ok": True, "folder": created}
        if parent_folder_name is not None:
            payload["resolved_parent_folder_id"] = effective_parent_id
            payload["parent_folder_name"] = parent_folder_name.strip()
        return json.dumps(payload, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"create_mail_folder: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"create_mail_folder: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


async def create_reply_draft(ctx: Context, message_id: str, comment: str | None = None) -> str:
    """Create a reply draft for a message, pre-populated with sender, subject (RE:), and quoted body.

    Optionally include a ``comment`` (reply text) to pre-fill the draft body.
    Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite.
    """
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {"error": "write_disabled", "message": "Set ENABLE_WRITE_OPERATIONS=true to enable create_reply_draft."}
        )

    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"create_reply_draft: message_id={message_id!r}")
    try:
        draft = await client.create_reply(message_id, comment=comment)
        return json.dumps({"ok": True, "message": draft}, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"create_reply_draft: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"create_reply_draft: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})
