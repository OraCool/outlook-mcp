"""Read-only Graph mail tools."""

from __future__ import annotations

import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from mcp.types import BlobResourceContents, ContentBlock, EmbeddedResource, ImageContent, TextContent

from outlook_mcp.auth.graph_client import MailFolderAmbiguousError, MailFolderNotFoundError
from outlook_mcp.auth.managed_identity import ManagedIdentityError, get_managed_identity_token
from outlook_mcp.auth.token_handler import GRAPH_AUTH_ERRORS
from outlook_mcp.config import get_settings
from outlook_mcp.storage.azure_blob import (
    STORAGE_RESOURCE,
    StorageConfigError,
    normalize_container_url,
    parse_allowed_prefixes,
    put_blob,
    validate_storage_key,
)
from outlook_mcp.tools._attachments import (
    ATTACHMENT_LIST_SELECT,
    guess_content_type,
    strip_content_bytes_from_attachments_list,
)
from outlook_mcp.tools._common import (
    email_json_for_tool_response,
    graph_message_to_model,
    make_graph_client,
    sanitize_client_error_message,
    tool_error_token,
)
from outlook_mcp.tools._notify import _preview, tool_log_info, tool_log_warning, tool_report_progress
from outlook_mcp.tools.mail_query_params import (
    build_inbox_odata_filter,
    build_search_kql_query,
    normalize_priority_filter,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

_DEFAULT_SELECT = (
    "id,subject,bodyPreview,body,receivedDateTime,sentDateTime,conversationId,"
    "internetMessageId,from,sender,toRecipients,ccRecipients,bccRecipients,isDraft,"
    "isRead,hasAttachments,importance,categories,flag"
)
_LIST_SELECT = (
    "id,subject,bodyPreview,receivedDateTime,sentDateTime,conversationId,"
    "internetMessageId,from,sender,toRecipients,isRead,hasAttachments,importance,categories,flag"
)


def _recipient_list(items: object) -> list[dict[str, str | None]]:
    """Graph recipient objects -> ``[{"address", "name"}]`` (same shape as ``to_recipients``)."""
    out: list[dict[str, str | None]] = []
    for item in items if isinstance(items, list) else []:
        ea = item.get("emailAddress") if isinstance(item, dict) else None
        if isinstance(ea, dict):
            out.append({"address": ea.get("address"), "name": ea.get("name")})
    return out


async def get_email(message_id: str, ctx: Context) -> str:
    """Fetch a single message by Graph message id (delegated: ``Mail.Read``)."""
    pid = _preview(message_id)
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"get_email: start message_id={pid}")
    await tool_report_progress(ctx, 10, 100, message="get_email: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="get_email: calling Graph")
        raw = await client.get_message(message_id, select=_DEFAULT_SELECT)
        await tool_report_progress(ctx, 80, 100, message="get_email: mapping response")
        model = graph_message_to_model(raw)
        await tool_report_progress(ctx, 100, 100, message="get_email: complete")
        settings = get_settings()
        payload = email_json_for_tool_response(model.model_dump(mode="json", by_alias=True), settings)
        payload["is_draft"] = raw.get("isDraft")
        # Cc/Bcc only in the full response level; minimal/redacted keep their existing recipient handling.
        if (getattr(settings, "pii_response_level", None) or "full").lower().strip() == "full":
            payload["cc_recipients"] = _recipient_list(raw.get("ccRecipients"))
            payload["bcc_recipients"] = _recipient_list(raw.get("bccRecipients"))
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
    except GRAPH_AUTH_ERRORS as e:
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


async def search_emails(
    query: str,
    ctx: Context,
    top: int = 25,
    read_filter: str = "any",
    received_on: str | None = None,
    received_after: str | None = None,
    received_before: str | None = None,
    priority_filter: str = "any",
) -> str:
    """Search the signed-in user's mailbox using **KQL** (Keyword Query Language).

    Graph uses ``$search`` on messages with ``ConsistencyLevel: eventual``.

    ``read_filter``: ``any`` (default), ``read``, or ``unread`` (adds ``read:yes`` / ``read:no``).

    ``priority_filter``: ``any`` (default), ``high``, ``medium``, or ``low`` — maps to Outlook
    message **importance** (Graph ``high`` / ``normal`` / ``low``). This is separate from
    classifier ``priority`` on ``categorize_email``.

    Date filters (UTC): ``received_on`` (YYYY-MM-DD, that calendar day), or
    ``received_after`` / ``received_before`` (YYYY-MM-DD for KQL day granularity).
    Do not combine ``received_on`` with ``received_after`` / ``received_before``.

    Example queries: ``from:user@contoso.com``, ``subject:invoice``,
    ``hasattachment:yes``, ``from:a@x.com AND subject:payment``. See
    https://learn.microsoft.com/en-us/graph/search-query-parameter
    """
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))
    try:
        pf = normalize_priority_filter(priority_filter)
        effective_query = build_search_kql_query(
            query,
            read_filter=read_filter,
            received_on=received_on,
            received_after=received_after,
            received_before=received_before,
            priority_filter=pf,
        )
    except ValueError as e:
        return json.dumps({"error": "invalid_parameters", "message": str(e)})
    await tool_log_info(
        ctx,
        f"search_emails: start has_query={bool(query)} query_len={len(query)} top={top} read_filter={read_filter!r} "
        f"priority_filter={pf!r}",
    )
    await tool_report_progress(ctx, 10, 100, message="search_emails: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="search_emails: calling Graph")
        data = await client.search_messages(effective_query, top=top, select=_LIST_SELECT)
        await tool_report_progress(ctx, 80, 100, message="search_emails: mapping results")
        items = data.get("value") or []
        settings = get_settings()
        models = [
            email_json_for_tool_response(graph_message_to_model(m).model_dump(mode="json", by_alias=True), settings)
            for m in items
        ]
        await tool_report_progress(ctx, 100, 100, message="search_emails: complete")
        return json.dumps(
            {
                "query": query,
                "effective_query": effective_query,
                "read_filter": read_filter,
                "priority_filter": pf,
                "messages": models,
                "count": len(models),
            }
        )
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


async def list_inbox(
    ctx: Context,
    top: int = 25,
    skip: int = 0,
    unread_only: bool = False,
    received_on: str | None = None,
    received_after: str | None = None,
    received_before: str | None = None,
    folder_id: str | None = None,
    folder_name: str | None = None,
    priority_filter: str = "any",
    sort_by_priority: bool = False,
) -> str:
    """List messages in a mail folder (newest first). Default folder is Inbox (well-known ``inbox``).

    When ``folder_id`` is set, list that folder (id from ``list_folders``, or well-known
    name such as ``sentitems``, ``drafts``, ``archive``).

    When ``folder_name`` is set (and ``folder_id`` is not), resolve the folder by
    case-insensitive ``displayName`` via Graph (folder tree walk). If none or multiple
    folders match, returns ``folder_not_found`` or ``folder_ambiguous`` errors.

    When ``unread_only`` is true, only ``isRead`` false.

    ``priority_filter``: ``any`` (default), ``high``, ``medium``, or ``low`` — OData filter on
    Graph message **importance** (``high`` / ``normal`` / ``low``). Separate from classifier
    ``priority`` on ``categorize_email``.

    When ``sort_by_priority`` is true, order by importance (high first) then ``receivedDateTime``
    descending.

    ``received_on`` (YYYY-MM-DD): messages received during that UTC calendar day.

    ``received_after`` / ``received_before``: ISO date (``YYYY-MM-DD``) or datetime;
    inclusive lower bound ``receivedDateTime ge``; exclusive upper ``receivedDateTime lt``
    (messages strictly before that instant). Do not set ``received_on`` together with
    ``received_after`` / ``received_before``.
    """
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))
    if folder_id and folder_name:
        return json.dumps(
            {
                "error": "invalid_parameters",
                "message": "Specify only one of folder_id or folder_name.",
            }
        )

    try:
        pf = normalize_priority_filter(priority_filter)
        inbox_filter = build_inbox_odata_filter(
            unread_only,
            received_on,
            received_after,
            received_before,
            priority_filter=pf,
        )
    except ValueError as e:
        return json.dumps({"error": "invalid_parameters", "message": str(e)})

    await tool_report_progress(ctx, 10, 100, message="list_inbox: start")

    effective_folder_id = folder_id
    if folder_name is not None:
        fn = folder_name.strip()
        if not fn:
            return json.dumps(
                {"error": "invalid_parameters", "message": "folder_name must be non-empty when set."}
            )
        try:
            await tool_report_progress(ctx, 25, 100, message="list_inbox: resolving folder_name")
            effective_folder_id = await client.resolve_mail_folder_id_by_display_name(fn)
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
        f"list_inbox: start top={top} skip={skip} unread_only={unread_only} "
        f"priority_filter={pf!r} sort_by_priority={sort_by_priority} "
        f"folder_id_set={bool(folder_id)} folder_name_set={folder_name is not None}",
    )
    try:
        await tool_report_progress(ctx, 40, 100, message="list_inbox: calling Graph")
        data = await client.list_inbox(
            top=top,
            skip=skip,
            select=_LIST_SELECT,
            inbox_filter=inbox_filter,
            folder_id=effective_folder_id,
            sort_by_priority=sort_by_priority,
        )
        await tool_report_progress(ctx, 80, 100, message="list_inbox: mapping messages")
        items = data.get("value") or []
        settings = get_settings()
        models = [
            email_json_for_tool_response(graph_message_to_model(m).model_dump(mode="json", by_alias=True), settings)
            for m in items
        ]
        await tool_report_progress(ctx, 100, 100, message="list_inbox: complete")
        out: dict[str, object] = {
            "messages": models,
            "count": len(models),
            "top": top,
            "skip": skip,
            "unread_only": unread_only,
            "priority_filter": pf,
            "sort_by_priority": sort_by_priority,
            "folder_id": effective_folder_id,
            "folder_name": folder_name.strip() if folder_name else None,
            "resolved_from_name": bool(folder_name),
            "received_on": received_on,
            "received_after": received_after,
            "received_before": received_before,
        }
        if inbox_filter:
            out["inbox_filter"] = inbox_filter
        return json.dumps(out)
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
    """List attachments metadata for a message (does not download file bytes).

    Use ``get_attachment_content`` to download a specific attachment's bytes as native
    multimodal content (an image the model can see, or an embedded document resource).
    """
    pid = _preview(message_id)
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))
    await tool_log_info(ctx, f"get_attachments: start message_id={pid}")
    await tool_report_progress(ctx, 10, 100, message="get_attachments: start")
    try:
        await tool_report_progress(ctx, 40, 100, message="get_attachments: calling Graph")
        data = await client.list_attachments(message_id, select=ATTACHMENT_LIST_SELECT)
        data = strip_content_bytes_from_attachments_list(data)
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


async def get_attachment_content(
    message_id: str, attachment_id: str, ctx: Context, as_resource: bool = False
) -> list[ContentBlock]:
    """Download one attachment's bytes and return them as native multimodal MCP content.

    By default, images become ``ImageContent`` so the model can visually see them; every other
    file type becomes an ``EmbeddedResource`` blob. Set ``as_resource=True`` to always get an
    ``EmbeddedResource`` (base64 text), including for images — use this when the goal is to
    save/forward the file's bytes rather than have the model look at it: when an image is
    delivered as ``ImageContent``, the model only ever sees the decoded picture, it never
    receives the base64 as literal text it could pass to a file-write tool.

    A leading ``TextContent`` block carries filename/size/content-type, since neither content
    type carries a filename field on its own. Attachments over ``MAX_MULTIMODAL_ATTACHMENT_BYTES``
    return a metadata-only error instead of the blob — use ``get_attachments`` first to check
    size for large files.
    """
    pid = _preview(message_id)
    settings = get_settings()
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return [TextContent(type="text", text=json.dumps(tool_error_token(e)))]

    await tool_log_info(ctx, f"get_attachment_content: start message_id={pid} attachment_id={_preview(attachment_id)}")
    try:
        meta = await client.get_attachment(message_id, attachment_id)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"get_attachment_content: http_error status={e.response.status_code}")
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "http_error",
                        "status_code": e.response.status_code,
                        "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
                    }
                ),
            )
        ]
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"get_attachment_content: network_error {type(e).__name__}")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))}),
            )
        ]

    if meta.get("@odata.type") != "#microsoft.graph.fileAttachment":
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "unsupported_attachment_type",
                        "odata_type": meta.get("@odata.type"),
                        "attachment": meta,
                    }
                ),
            )
        ]

    size = meta.get("size") or 0
    if size > settings.max_multimodal_attachment_bytes:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "attachment_too_large_for_inline",
                        "size": size,
                        "limit": settings.max_multimodal_attachment_bytes,
                        "message": (
                            "Use get_attachments for metadata; this attachment exceeds the "
                            "inline multimodal size limit."
                        ),
                    }
                ),
            )
        ]

    try:
        raw_bytes, header_content_type = await client.get_attachment_raw_bytes(message_id, attachment_id)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"get_attachment_content: http_error status={e.response.status_code}")
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": "http_error",
                        "status_code": e.response.status_code,
                        "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
                    }
                ),
            )
        ]
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"get_attachment_content: network_error {type(e).__name__}")
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))}),
            )
        ]

    name = meta.get("name") or "attachment"
    content_type = meta.get("contentType") or header_content_type or guess_content_type(name, None)
    b64 = base64.b64encode(raw_bytes).decode()

    blocks: list[ContentBlock] = [
        TextContent(
            type="text",
            text=json.dumps({"name": name, "size": len(raw_bytes), "content_type": content_type}),
        )
    ]
    is_image = content_type.startswith("image/")
    if not as_resource and is_image:
        blocks.append(ImageContent(type="image", data=b64, mimeType=content_type))
    else:
        # When forcing an image through as_resource, mask mimeType as a generic binary type.
        # MCP clients (e.g. Claude Desktop) render ANY block with an image/* mimeType inline
        # and truncate the response before the base64 ever reaches the model as text — masking
        # it is the only way as_resource actually delivers extractable bytes for images. The
        # real content type is still available in the leading TextContent metadata block.
        resource_mime_type = "application/octet-stream" if (as_resource and is_image) else content_type
        blocks.append(
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri=f"attachment://{message_id}/{attachment_id}",
                    mimeType=resource_mime_type,
                    blob=b64,
                ),
            )
        )
    await tool_log_info(ctx, "get_attachment_content: complete")
    return blocks


_TOO_LARGE_JSON = json.dumps({"ok": False, "error": "too_large"})


async def _download_file_attachment(
    client: Any, message_id: str, attachment_id: str, ctx: Context, tool: str, max_bytes: int | None = None
) -> tuple[str | None, str, bytes, str]:
    """Fetch a file attachment's metadata and bytes.

    Returns ``(error_json, name, raw_bytes, content_type)``; ``error_json`` is None on success.
    With ``max_bytes``, a metadata ``size`` above the cap returns ``too_large`` before any download.
    """
    try:
        meta = await client.get_attachment(message_id, attachment_id)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"{tool}: http_error status={e.response.status_code}")
        return _http_error_json(e), "", b"", ""
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"{tool}: network_error {type(e).__name__}")
        return _network_error_json(e), "", b"", ""

    if meta.get("@odata.type") != "#microsoft.graph.fileAttachment":
        err = json.dumps(
            {
                "error": "unsupported_attachment_type",
                "odata_type": meta.get("@odata.type"),
                "attachment": meta,
            }
        )
        return err, "", b"", ""

    meta_size = meta.get("size")
    if max_bytes is not None and isinstance(meta_size, int) and meta_size > max_bytes:
        return _TOO_LARGE_JSON, "", b"", ""

    try:
        raw_bytes, header_content_type = await client.get_attachment_raw_bytes(message_id, attachment_id)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"{tool}: http_error status={e.response.status_code}")
        return _http_error_json(e), "", b"", ""
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"{tool}: network_error {type(e).__name__}")
        return _network_error_json(e), "", b"", ""

    name = meta.get("name") or "attachment"
    content_type = meta.get("contentType") or header_content_type or guess_content_type(name, None)
    return None, name, raw_bytes, content_type


_MAX_CHARS_CEILING = 1_000_000


async def get_attachment_text(message_id: str, attachment_id: str, ctx: Context, max_chars: int = 200000) -> str:
    """Return the text of a PDF or plain-text attachment (nothing is logged about content)."""
    s = get_settings()
    max_chars = max(1, min(int(max_chars), _MAX_CHARS_CEILING))
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"get_attachment_text: start message_id={_preview(message_id)}")
    error, _name, raw, _ct = await _download_file_attachment(
        client, message_id, attachment_id, ctx, "get_attachment_text", max_bytes=s.attachment_text_max_bytes
    )
    if error is not None:
        return _scrub_attachment_text_error(error)
    if len(raw) > s.attachment_text_max_bytes:
        return _TOO_LARGE_JSON
    if raw.lstrip(b"\x00 \t\r\n")[:5] != b"%PDF-":
        text = _decode_text_attachment(raw)
        if text is None:
            return json.dumps({"ok": False, "error": "unsupported_format"})
        await tool_log_info(ctx, "get_attachment_text: complete")
        return json.dumps(
            {"ok": True, "format": "text", "text": text[:max_chars], "truncated": len(text) > max_chars}
        )
    try:
        pages, text, page_limited = await _run_pdf_extraction(
            raw, max_chars, s.attachment_text_max_pages, s.attachment_text_timeout_seconds
        )
    except TimeoutError:
        await tool_log_warning(ctx, "get_attachment_text: timeout")
        return json.dumps({"ok": False, "error": "unreadable"})
    except Exception:  # noqa: BLE001 - pypdf raises many types (incl. DependencyError); never leak details
        await tool_log_warning(ctx, "get_attachment_text: unreadable")
        return json.dumps({"ok": False, "error": "unreadable"})
    truncated = page_limited or len(text) > max_chars
    await tool_log_info(ctx, "get_attachment_text: complete")
    return json.dumps(
        {"ok": True, "format": "pdf", "pages": pages, "text": text[:max_chars], "truncated": truncated}
    )


# Share of control characters (other than tab, newlines, form feed) above which bytes are treated as binary.
_TEXT_MAX_CONTROL_RATIO = 0.01


def _decode_text_attachment(raw: bytes) -> str | None:
    """Decode a plain-text attachment (TXT, CSV, XML, JSON, ...) or return ``None`` for binary data.

    UTF-8 (with or without BOM) and BOM-marked UTF-16 are accepted; anything that does not decode
    strictly or is mostly control characters is binary. The content is returned as-is: XML is not
    parsed, so no entity expansion or external lookups can happen.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        data, encoding = raw[3:], "utf-8"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        data, encoding = raw, "utf-16"
    else:
        data, encoding = raw, "utf-8"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r\f")
    if "\x00" in text or controls > len(text) * _TEXT_MAX_CONTROL_RATIO:
        return None
    return text


def _scrub_attachment_text_error(error_json: str) -> str:
    """Strict error shape for get_attachment_text: no attachment name/metadata, no Graph body text."""
    try:
        data = json.loads(error_json)
    except ValueError:
        return json.dumps({"ok": False, "error": "unreadable"})
    kind = data.get("error")
    if kind == "unsupported_attachment_type":
        return json.dumps({"ok": False, "error": "unsupported_format"})
    if kind == "http_error":
        return json.dumps({"error": "http_error", "status_code": data.get("status_code")})
    if kind == "network_error":
        return json.dumps({"error": "network_error"})
    return error_json


# PDF parsing runs on its own small pool so a slow or stuck file can never starve the default
# ``asyncio.to_thread`` pool used by the other tools. A worker thread cannot be cancelled: on timeout
# the caller gets "unreadable" while the thread finishes in the background (bounded by the byte and
# page caps). The semaphore slot is held until the thread really ends, so at most
# ``_PDF_MAX_WORKERS`` extractions run and nothing queues up behind stuck ones.
_PDF_MAX_WORKERS = 2
_PDF_EXECUTOR = ThreadPoolExecutor(max_workers=_PDF_MAX_WORKERS, thread_name_prefix="pdf-text")
_pdf_slots: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None


def _pdf_semaphore() -> asyncio.Semaphore:
    """One semaphore per event loop (asyncio primitives are bound to the loop that first waits on them)."""
    global _pdf_slots
    loop = asyncio.get_running_loop()
    if _pdf_slots is None or _pdf_slots[0] is not loop:
        _pdf_slots = (loop, asyncio.Semaphore(_PDF_MAX_WORKERS))
    return _pdf_slots[1]


async def _run_pdf_extraction(
    raw: bytes, max_chars: int, max_pages: int, timeout: float
) -> tuple[int, str, bool]:
    """Run ``_extract_pdf_text`` on the bounded pool; ``TimeoutError`` if no slot or no result in time."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    sem = _pdf_semaphore()
    await asyncio.wait_for(sem.acquire(), timeout=timeout)  # all slots busy for too long -> TimeoutError

    def _release(_f: object) -> None:
        try:
            loop.call_soon_threadsafe(sem.release)
        except RuntimeError:  # loop already closed (shutdown): nothing left to release for
            pass

    try:
        cf = _PDF_EXECUTOR.submit(_extract_pdf_text, raw, max_chars, max_pages)
    except BaseException:
        sem.release()
        raise
    cf.add_done_callback(_release)
    remaining = max(deadline - loop.time(), 0.0)
    # shield: a timeout must not detach the slot from the still-running thread.
    return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(cf)), timeout=remaining)


def _extract_pdf_text(raw: bytes, max_chars: int, max_pages: int) -> tuple[int, str, bool]:
    """Return (page_count, text, page_limited). Text stops just above ``max_chars`` so truncation is detectable.

    Encrypted PDFs are tried with the empty password only (AES needs ``cryptography``, which ships
    with pyjwt[crypto]; a pypdf DependencyError would surface as ``unreadable``).
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("encrypted")
    n_pages = len(reader.pages)
    parts: list[str] = []
    total = 0
    for i in range(min(n_pages, max_pages)):
        t = reader.pages[i].extract_text() or ""
        parts.append(t)
        total += len(t) + 1
        if total > max_chars:
            break
    return n_pages, "\n".join(parts), n_pages > max_pages


def _http_error_json(e: httpx.HTTPStatusError) -> str:
    return json.dumps(
        {
            "error": "http_error",
            "status_code": e.response.status_code,
            "message": sanitize_client_error_message(e.response.text[:2000], max_len=2000),
        }
    )


def _network_error_json(e: httpx.HTTPError) -> str:
    return json.dumps({"error": "network_error", "message": sanitize_client_error_message(str(e))})


def _safe_attachment_filename(name: str | None) -> str | None:
    """Reduce an attachment's own (sender-controlled) name to a plain file name, or ``None``.

    Keeps only the last component after ``/`` or ``\\``, drops control characters, and rejects
    empty, ``.`` and ``..`` so the name can never point outside the target directory.
    """
    if not name:
        return None
    last = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in last if ord(ch) >= 32 and ord(ch) != 127).strip()
    if cleaned in ("", ".", ".."):
        return None
    return cleaned


async def save_attachment_to_path(message_id: str, attachment_id: str, path: str, ctx: Context) -> str:
    """Download one attachment and write it directly to local disk (no base64 round-trip).

    ``path`` is either the exact target file path, or an existing directory — in which case the
    attachment's own filename is used. Missing parent directories are created. This is the
    reliable way to save an attachment (especially an image): routing bytes through MCP tool
    responses hits context/token limits and, for images, MCP clients render ``image/*`` content
    inline and truncate the response before the base64 ever reaches the model as usable text.
    Requires ENABLE_WRITE_OPERATIONS=true (this tool writes to the local filesystem).
    """
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable save_attachment_to_path.",
            }
        )
    if not path or not path.strip():
        return json.dumps({"error": "validation_error", "message": "path must be a non-empty string."})

    pid = _preview(message_id)
    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"save_attachment_to_path: start message_id={pid} attachment_id={_preview(attachment_id)}")
    error, name, raw_bytes, content_type = await _download_file_attachment(
        client, message_id, attachment_id, ctx, "save_attachment_to_path"
    )
    if error is not None:
        return error

    try:
        target = Path(path).expanduser()
        if target.exists() and target.is_dir():
            # The attachment name comes from the email sender: never let it leave the directory.
            safe_name = _safe_attachment_filename(name)
            base = target.resolve()
            candidate = (base / safe_name).resolve() if safe_name else None
            if candidate is None or candidate.parent != base or not candidate.is_relative_to(base):
                await tool_log_warning(ctx, "save_attachment_to_path: unsafe attachment name")
                return json.dumps(
                    {
                        "error": "validation_error",
                        "message": "Attachment name is not a safe file name; pass an explicit file path instead.",
                    }
                )
            target = candidate
            name = safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw_bytes)
    except OSError as e:
        await tool_log_warning(ctx, f"save_attachment_to_path: filesystem_error {type(e).__name__}")
        return json.dumps({"error": "filesystem_error", "message": sanitize_client_error_message(str(e))})

    await tool_log_info(ctx, "save_attachment_to_path: complete")
    return json.dumps(
        {"ok": True, "path": str(target), "name": name, "size": len(raw_bytes), "content_type": content_type}
    )


def _storage_http_client() -> httpx.Client:
    return httpx.Client(timeout=120.0)


async def save_attachment_to_storage(message_id: str, attachment_id: str, key: str, ctx: Context) -> str:
    """Download one attachment and write it to the configured private Azure Blob container.

    Uses the app's managed identity (no secrets). ``key`` is the blob name (``/`` separates
    folders). Nothing about the key, file name or content is logged. Requires
    ENABLE_WRITE_OPERATIONS=true and GRAPH_TRUST_REQUEST_HEADERS=false (the storage identity is the
    server's own, so the Graph identity must be too; otherwise returns ``configuration_error``).
    """
    s = get_settings()
    if not s.enable_write_operations:
        return json.dumps(
            {
                "error": "write_disabled",
                "message": "Set ENABLE_WRITE_OPERATIONS=true to enable save_attachment_to_storage.",
            }
        )
    if s.graph_trust_request_headers:
        # Storage writes use the server's managed identity. If callers may bring their own Graph
        # token via headers, any caller could make the server write into its storage account.
        return json.dumps(
            {
                "error": "configuration_error",
                "message": (
                    "save_attachment_to_storage writes with the server's managed identity; it requires "
                    "GRAPH_TRUST_REQUEST_HEADERS=false so the Graph identity is the server's own."
                ),
            }
        )
    if s.attachment_storage != "azure_blob" or not s.attachment_blob_container_url.strip():
        return json.dumps(
            {
                "error": "configuration_error",
                "message": "Set ATTACHMENT_STORAGE=azure_blob and ATTACHMENT_BLOB_CONTAINER_URL.",
            }
        )
    try:
        container = normalize_container_url(s.attachment_blob_container_url)
    except StorageConfigError as e:
        return json.dumps({"error": "configuration_error", "message": str(e)})
    try:
        prefixes = parse_allowed_prefixes(s.attachment_allowed_prefixes)
    except StorageConfigError as e:
        return json.dumps({"error": "configuration_error", "message": str(e)})
    try:
        norm_key = validate_storage_key(key, prefixes)
    except ValueError as e:
        return json.dumps({"error": "invalid_key", "reason": str(e)})

    try:
        client = make_graph_client(ctx)
    except GRAPH_AUTH_ERRORS as e:
        return json.dumps(tool_error_token(e))

    await tool_log_info(ctx, f"save_attachment_to_storage: start message_id={_preview(message_id)}")
    error, _name, raw_bytes, content_type = await _download_file_attachment(
        client, message_id, attachment_id, ctx, "save_attachment_to_storage"
    )
    if error is not None:
        return error

    try:
        token, _expires = await asyncio.to_thread(
            get_managed_identity_token, STORAGE_RESOURCE, client_id=s.azure_client_id
        )
    except ManagedIdentityError as e:
        await tool_log_warning(ctx, "save_attachment_to_storage: managed_identity_error")
        return json.dumps(tool_error_token(e))

    def _put() -> None:
        with _storage_http_client() as http:
            put_blob(container, norm_key, raw_bytes, content_type, token, http)

    try:
        await asyncio.to_thread(_put)
    except httpx.HTTPStatusError as e:
        await tool_log_warning(ctx, f"save_attachment_to_storage: storage_error status={e.response.status_code}")
        return json.dumps(
            {
                "error": "storage_error",
                "status_code": e.response.status_code,
                "storage_error_code": e.response.headers.get("x-ms-error-code", ""),
            }
        )
    except httpx.HTTPError as e:
        await tool_log_warning(ctx, f"save_attachment_to_storage: network_error {type(e).__name__}")
        return json.dumps({"error": "network_error", "message": "Could not reach Azure Blob Storage."})
    except Exception as e:  # noqa: BLE001 - never let URL-encoding/transport surprises escape with key text
        await tool_log_warning(ctx, f"save_attachment_to_storage: internal_error {type(e).__name__}")
        return json.dumps({"error": "storage_error", "message": "Could not write to Azure Blob Storage."})

    await tool_log_info(ctx, "save_attachment_to_storage: complete")
    return json.dumps({"ok": True, "queued": True, "key": norm_key, "bytes": len(raw_bytes)})


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
    except GRAPH_AUTH_ERRORS as e:
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
    except GRAPH_AUTH_ERRORS as e:
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
        await tool_log_warning(ctx, f"list_folders: network_error {type(e).__name__}")
        return json.dumps(
            {"error": "network_error", "message": sanitize_client_error_message(str(e))},
        )
