"""Read-only Graph mail tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.config import get_settings
from outlook_mcp.tools._common import (
    email_json_for_tool_response,
    graph_message_to_model,
    make_graph_client,
    sanitize_client_error_message,
    tool_error_token,
)
from outlook_mcp.tools._notify import _preview, tool_log_info, tool_log_warning, tool_report_progress

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

_DEFAULT_SELECT = (
    "id,subject,bodyPreview,body,receivedDateTime,sentDateTime,conversationId,"
    "internetMessageId,from,sender,toRecipients,isRead,hasAttachments,categories"
)
_LIST_SELECT = (
    "id,subject,bodyPreview,receivedDateTime,sentDateTime,conversationId,"
    "internetMessageId,from,sender,toRecipients,isRead,hasAttachments,categories"
)


async def get_email(message_id: str, ctx: Context) -> str:
    """Fetch a single message by Graph message id (delegated: ``Mail.Read``)."""
    pid = _preview(message_id)
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"get_email: start message_id={pid}")
    await tool_report_progress(ctx, 10, 100, message="get_email: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="get_email: calling Graph")
        raw = await client.get_message(message_id, select=_DEFAULT_SELECT)
        await tool_report_progress(ctx, 80, 100, message="get_email: mapping response")
        model = graph_message_to_model(raw)
        await tool_report_progress(ctx, 100, 100, message="get_email: complete")
        payload = email_json_for_tool_response(
            model.model_dump(mode="json", by_alias=True),
            get_settings(),
        )
        return json.dumps(payload, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"get_email: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"get_email: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )


async def get_thread(conversation_id: str, ctx: Context, top: int = 50) -> str:
    """List messages in a thread by ``conversationId``."""
    cid = _preview(conversation_id)
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"get_thread: start conversation_id={cid} top={top}")
    await tool_report_progress(ctx, 10, 100, message="get_thread: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="get_thread: calling Graph")
        data = await client.list_messages_by_conversation(
            conversation_id, top=top, select=_LIST_SELECT
        )
        await tool_report_progress(ctx, 80, 100, message="get_thread: mapping messages")
        items = data.get("value") or []
        settings = get_settings()
        models = [
            email_json_for_tool_response(graph_message_to_model(m).model_dump(mode="json", by_alias=True), settings)
            for m in items
        ]
        await tool_report_progress(ctx, 100, 100, message="get_thread: complete")
        return json.dumps({"conversation_id": conversation_id, "messages": models, "count": len(models)})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"get_thread: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"get_thread: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )


async def search_emails(query: str, ctx: Context, top: int = 25) -> str:
    """Search the signed-in user's mailbox using **KQL** (Keyword Query Language).

    Graph uses ``$search`` on messages with ``ConsistencyLevel: eventual``.

    Example queries: ``from:user@contoso.com``, ``subject:invoice``,
    ``received:2024-01-01..2024-12-31``, ``hasattachment:yes``,
    ``from:a@x.com AND subject:payment``. See
    https://learn.microsoft.com/en-us/graph/search-query-parameter
    """
    qprev = _preview(query, max_len=24)
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"search_emails: start query={qprev!r} top={top}")
    await tool_report_progress(ctx, 10, 100, message="search_emails: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="search_emails: calling Graph")
        data = await client.search_messages(query, top=top, select=_LIST_SELECT)
        await tool_report_progress(ctx, 80, 100, message="search_emails: mapping results")
        items = data.get("value") or []
        settings = get_settings()
        models = [
            email_json_for_tool_response(graph_message_to_model(m).model_dump(mode="json", by_alias=True), settings)
            for m in items
        ]
        await tool_report_progress(ctx, 100, 100, message="search_emails: complete")
        return json.dumps({"query": query, "messages": models, "count": len(models)})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"search_emails: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"search_emails: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )


async def list_inbox(ctx: Context, top: int = 25, skip: int = 0) -> str:
    """List recent Inbox messages (newest first)."""
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"list_inbox: start top={top} skip={skip}")
    await tool_report_progress(ctx, 10, 100, message="list_inbox: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="list_inbox: calling Graph")
        data = await client.list_inbox(top=top, skip=skip, select=_LIST_SELECT)
        await tool_report_progress(ctx, 80, 100, message="list_inbox: mapping messages")
        items = data.get("value") or []
        settings = get_settings()
        models = [
            email_json_for_tool_response(graph_message_to_model(m).model_dump(mode="json", by_alias=True), settings)
            for m in items
        ]
        await tool_report_progress(ctx, 100, 100, message="list_inbox: complete")
        return json.dumps({"messages": models, "count": len(models), "top": top, "skip": skip})
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"list_inbox: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"list_inbox: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )


async def get_attachments(message_id: str, ctx: Context) -> str:
    """List attachments metadata for a message (does not download file bytes)."""
    pid = _preview(message_id)
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"get_attachments: start message_id={pid}")
    await tool_report_progress(ctx, 10, 100, message="get_attachments: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="get_attachments: calling Graph")
        data = await client.list_attachments(message_id)
        await tool_report_progress(ctx, 100, 100, message="get_attachments: complete")
        return json.dumps(data, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"get_attachments: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"get_attachments: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )


async def list_master_categories(ctx: Context, top: int = 500) -> str:
    """List Outlook master categories (name and color) for the signed-in user.

    These are the mailbox category definitions (not the same as per-message ``categories``
    strings or the AR ``categorize_email`` taxonomy). Requires delegated
    ``MailboxSettings.Read`` on the token; without it Graph returns 403.
    ``top`` is Graph ``$top`` (default 500; increase if your tenant defines many categories).

    https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories
    """
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"list_master_categories: start top={top}")
    await tool_report_progress(ctx, 10, 100, message="list_master_categories: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="list_master_categories: calling Graph")
        data = await client.list_master_categories(top=top)
        await tool_report_progress(ctx, 100, 100, message="list_master_categories: complete")
        items = data.get("value") or []
        return json.dumps({"categories": items, "count": len(items)}, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"list_master_categories: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"list_master_categories: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )


async def list_folders(ctx: Context, top: int = 100) -> str:
    """List mail folders for the signed-in user (id, displayName, parentFolderId, childFolderCount, totalItemCount).

    Useful for discovering folder IDs for ``move_email``.
    """
    try:
        client = make_graph_client(ctx)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"list_folders: start top={top}")
    try:
        data = await client.list_folders(top=top)
        items = data.get("value") or []
        folders = [
            {
                "id": f.get("id"),
                "displayName": f.get("displayName"),
                "parentFolderId": f.get("parentFolderId"),
                "childFolderCount": f.get("childFolderCount"),
                "totalItemCount": f.get("totalItemCount"),
                "unreadItemCount": f.get("unreadItemCount"),
            }
            for f in items
        ]
        return json.dumps({"folders": folders, "count": len(folders)}, indent=2)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"list_folders: http_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "http_error",
                "status_code": e.response.status_code,
                "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
            }
        )
    except httpx.HTTPError as e:
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )
