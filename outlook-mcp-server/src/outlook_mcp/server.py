"""Outlook MCP server entrypoint (stdio + streamable-http)."""

from __future__ import annotations

import sys
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ContentBlock
from starlette.requests import Request
from starlette.responses import JSONResponse

from outlook_mcp.config import get_settings
from outlook_mcp.tools import (
    email_classifier,
    email_drafter,
    email_extractor,
    email_reader,
    email_summarizer,
    email_writer,
    mailbox_settings,
)


def build_mcp() -> MCPServer:
    s = get_settings()
    mcp = MCPServer(
        name="outlook-mcp",
        instructions=(
            "Microsoft Outlook / Graph mail tools for AR Email Management. "
            "Auth: X-Graph-Token header; or enable OAuth and use GET /oauth/login then X-OAuth-Session; "
            "or GRAPH_OAUTH_TOKEN_CACHE_PATH after outlook-mcp-oauth-device; or GRAPH_DEV_TOKEN for local dev. "
            "search_emails: the query parameter is KQL (Keyword Query Language) against the signed-in user's mailbox; "
            "Graph uses eventual consistency for this API. Reference: "
            "https://learn.microsoft.com/en-us/graph/search-query-parameter"
        ),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "ok", "service": "outlook-mcp"})

    if s.graph_oauth_enabled and s.graph_oauth_client_id.strip():
        from outlook_mcp.auth.oauth_routes import register_oauth_routes

        register_oauth_routes(mcp)

    @mcp.tool()
    async def get_email(message_id: str, ctx: Context) -> str:
        """Fetch one message by Graph message id (includes full body and bodyPreview)."""
        return await email_reader.get_email(message_id, ctx)

    @mcp.tool()
    async def get_thread(conversation_id: str, ctx: Context, top: int = 50) -> str:
        """Fetch messages sharing the same conversationId (thread).

        Omits the full message body by default; use ``get_email`` for body text.
        Each item includes ``bodyPreview`` and metadata.
        """
        return await email_reader.get_thread(conversation_id, ctx, top=top)

    @mcp.tool()
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
        """Search the signed-in user's mailbox using KQL (Keyword Query Language).

        Microsoft Graph applies the query via ``$search`` on ``/me/messages`` with
        ``ConsistencyLevel: eventual`` (eventual consistency).

        Results omit the full message body by default; use ``get_email`` for body text.
        Each hit includes ``bodyPreview`` and metadata.

        ``read_filter``: ``any`` (default), ``read``, or ``unread``.

        Date filters (UTC, YYYY-MM-DD for KQL): ``received_on`` (single day), or
        ``received_after`` / ``received_before`` (range or open-ended). Do not combine
        ``received_on`` with ``received_after`` / ``received_before``.

        ``priority_filter``: ``any`` (default), ``high``, ``medium``, or ``low`` — Outlook
        message importance (Graph ``high`` / ``normal`` / ``low``), not classifier priority.

        Examples (combine with AND / OR where supported):
        - ``from:alice@contoso.com``
        - ``subject:invoice``
        - ``hasattachment:yes``
        - ``from:bob@contoso.com AND subject:payment``

        Full syntax and limitations:
        https://learn.microsoft.com/en-us/graph/search-query-parameter
        """
        return await email_reader.search_emails(
            query,
            ctx,
            top=top,
            read_filter=read_filter,
            received_on=received_on,
            received_after=received_after,
            received_before=received_before,
            priority_filter=priority_filter,
        )

    @mcp.tool()
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
        """List messages in a mail folder (default: Inbox).

        Omits the full message body by default; use ``get_email`` for body text.
        Each item includes ``bodyPreview`` and metadata.
        When ``unread_only`` is true, only messages with ``isRead`` false are returned.

        ``folder_id``: Graph folder id from ``list_folders``, or a well-known name (e.g.
        ``inbox``, ``sentitems``, ``drafts``, ``archive``). Omit for Inbox.

        ``folder_name``: resolve folder by display name (case-insensitive). Do not set
        together with ``folder_id``. If no match or multiple matches, returns an error.

        ``received_on`` (YYYY-MM-DD): that UTC calendar day only.
        ``received_after`` / ``received_before``: ISO date or datetime; lower bound
        inclusive, upper bound exclusive. Do not set ``received_on`` together with
        ``received_after`` / ``received_before``.

        ``priority_filter``: ``any``, ``high``, ``medium``, or ``low`` (Outlook importance).
        ``sort_by_priority``: when true, order by importance then newest first.
        """
        return await email_reader.list_inbox(
            ctx,
            top=top,
            skip=skip,
            unread_only=unread_only,
            received_on=received_on,
            received_after=received_after,
            received_before=received_before,
            folder_id=folder_id,
            folder_name=folder_name,
            priority_filter=priority_filter,
            sort_by_priority=sort_by_priority,
        )

    @mcp.tool()
    async def get_attachments(message_id: str, ctx: Context) -> str:
        """List attachment metadata for a message (id, name, contentType, size — never file bytes).

        Use ``get_attachment_content`` with an ``id`` from this list to download a specific
        attachment's bytes.
        """
        return await email_reader.get_attachments(message_id, ctx)

    @mcp.tool()
    async def get_attachment_content(
        message_id: str, attachment_id: str, ctx: Context, as_resource: bool = False
    ) -> list[ContentBlock]:
        """Download one attachment's bytes and return them as native multimodal content.

        By default, images are returned as an ``ImageContent`` block the model can see
        directly; every other file type (PDF, Office docs, etc.) is returned as an
        ``EmbeddedResource`` blob. Set ``as_resource=True`` to always get an ``EmbeddedResource``
        instead (base64 text, ``mimeType`` deliberately generic even for images — MCP clients
        render an image/* mimeType inline and truncate the response before the base64 reaches
        the model as usable text). A leading text block carries the filename/size/real
        content-type either way. Attachments larger than ``MAX_MULTIMODAL_ATTACHMENT_BYTES``
        (default 8MB) return a metadata-only error instead of the blob — check size with
        ``get_attachments`` first for large files.

        To actually save an attachment to local disk, prefer ``save_attachment_to_path`` over
        ``as_resource=True`` — it writes the file directly server-side with no base64 round-trip
        through the tool response at all, so it isn't subject to context/token limits either.
        """
        return await email_reader.get_attachment_content(message_id, attachment_id, ctx, as_resource=as_resource)

    @mcp.tool()
    async def save_attachment_to_path(message_id: str, attachment_id: str, path: str, ctx: Context) -> str:
        """Download one attachment and write it directly to local disk (no base64 round-trip).

        ``path`` is either the exact target file path, or an existing directory — in which case
        the attachment's own filename is used. Missing parent directories are created
        automatically. Requires ENABLE_WRITE_OPERATIONS=true (this tool writes to the local
        filesystem the server process runs on, not to Outlook).
        """
        return await email_reader.save_attachment_to_path(message_id, attachment_id, path, ctx)

    @mcp.tool()
    async def list_master_categories(ctx: Context, top: int = 500) -> str:
        """List Outlook master categories (display name and color) for the signed-in user.

        Not the same as message ``categories`` tags or the AR email classifier taxonomy.
        Requires delegated ``MailboxSettings.Read`` (add to app registration / token scopes).
        ``top`` is Graph ``$top`` (default 500).

        https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories
        """
        return await email_reader.list_master_categories(ctx, top=top)

    @mcp.tool()
    async def categorize_email(message_id: str, ctx: Context) -> str:
        """Classify email via MCP sampling (falls back to raw email if sampling unavailable)."""
        return await email_classifier.categorize_email(message_id, ctx)

    @mcp.tool()
    async def apply_llm_category_to_email(message_id: str, ctx: Context) -> str:
        """Classify via MCP sampling, then set Outlook message categories to that label.

        Requires ENABLE_WRITE_OPERATIONS=true and delegated Mail.ReadWrite. Replaces existing
        categories on the message with the single AR taxonomy label from the classifier (same
        taxonomy as categorize_email).
        """
        return await email_classifier.apply_llm_category_to_email(message_id, ctx)

    @mcp.tool()
    async def set_message_categories(
        ctx: Context,
        message_id: str,
        categories: list[str],
    ) -> str:
        """Set Outlook category tags on a message (replaces existing categories).

        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite. Use ``apply_llm_category_to_email``
        to set the category from LLM classification in one step.
        """
        return await email_writer.set_message_categories(ctx, message_id, categories)

    @mcp.tool()
    async def extract_email_data(message_id: str, ctx: Context) -> str:
        """Extract structured fields via MCP sampling (falls back if sampling unavailable)."""
        return await email_extractor.extract_email_data(message_id, ctx)

    @mcp.tool()
    async def summarize_email(message_id: str, ctx: Context) -> str:
        """Summarize a single email: 1-2 sentence summary with key entity extraction.

        Uses MCP sampling to produce a concise summary capturing intent and key financial
        context. Falls back to raw email JSON if sampling unavailable.
        """
        return await email_summarizer.summarize_email(message_id, ctx)

    @mcp.tool()
    async def summarize_thread(conversation_id: str, ctx: Context, top: int = 50) -> str:
        """Summarize an entire email thread: progression, key facts, commitments, and state.

        Fetches all messages sharing the conversationId and produces a thread summary via
        MCP sampling. Useful for long threads where individual email context is insufficient.
        """
        return await email_summarizer.summarize_thread(conversation_id, ctx, top=top)

    @mcp.tool()
    async def draft_reply(
        message_id: str,
        ctx: Context,
        classification_context: str | None = None,
    ) -> str:
        """Generate an AI-powered draft reply for an email via MCP sampling.

        Produces professional AR reply text based on the email content and optional
        classification context. Does NOT create an Outlook draft — use ``create_draft``
        to persist the generated text. Requires MCP sampling support on the client.
        """
        return await email_drafter.draft_reply(message_id, ctx, classification_context=classification_context)

    @mcp.tool()
    async def send_email(
        ctx: Context,
        subject: str,
        body_text: str,
        to_addresses: list[str],
        content_type: str = "Text",
        save_to_sent_items: bool = True,
        attachments: list[dict] | None = None,
    ) -> str:
        """Send email (requires ENABLE_WRITE_OPERATIONS=true and Mail.Send).

        Optional ``attachments``: list of ``{"filename": str | None, "content_type": str | None,
        "content_base64": str | None, "file_path": str | None, "is_inline": bool}`` — exactly
        one of ``content_base64``/``file_path`` per entry. Prefer ``file_path`` (the server reads
        the file itself from local disk) over ``content_base64`` for anything but tiny files:
        transcribing a large file's base64 content as a literal argument value is slow and
        error-prone for the calling model. ``filename`` defaults to the path's basename when
        ``file_path`` is used. Files over Graph's small-attachment limit (3MB) automatically go
        through a draft-then-send fallback (see tool docstring); the response includes
        ``used_draft_path: true`` when that happens.
        """
        return await email_writer.send_email(
            ctx,
            subject=subject,
            body_text=body_text,
            to_addresses=to_addresses,
            content_type=content_type,
            save_to_sent_items=save_to_sent_items,
            attachments=attachments,
        )

    @mcp.tool()
    async def send_draft_email(ctx: Context, draft_id: str) -> str:
        """Send an existing draft by Graph message id (requires ENABLE_WRITE_OPERATIONS=true and Mail.Send)."""
        return await email_writer.send_draft_email(ctx, draft_id=draft_id)

    @mcp.tool()
    async def create_draft(
        ctx: Context,
        subject: str,
        body_text: str,
        to_addresses: list[str] | None = None,
        content_type: str = "Text",
        attachments: list[dict] | None = None,
    ) -> str:
        """Create a draft message (requires ENABLE_WRITE_OPERATIONS=true).

        Optional ``attachments``: list of ``{"filename": str | None, "content_type": str | None,
        "content_base64": str | None, "file_path": str | None, "is_inline": bool}`` — exactly
        one of ``content_base64``/``file_path`` per entry; prefer ``file_path`` for anything but
        tiny files (see ``send_email`` for why). Response includes an ``attachments`` list
        (id/name/size/contentType) for what was attached.
        """
        return await email_writer.create_draft(
            ctx,
            subject=subject,
            body_text=body_text,
            to_addresses=to_addresses,
            content_type=content_type,
            attachments=attachments,
        )

    @mcp.tool()
    async def mark_as_read(ctx: Context, message_id: str, is_read: bool = True) -> str:
        """Mark a message as read or unread (requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite)."""
        return await email_writer.mark_as_read(ctx, message_id, is_read=is_read)

    @mcp.tool()
    async def set_email_priority(ctx: Context, message_id: str, priority: str) -> str:
        """Set Outlook message importance: HIGH, MEDIUM, or LOW (case-insensitive; Graph high/normal/low).

        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite. Distinct from classifier
        priority on ``categorize_email``.
        """
        return await email_writer.set_email_priority(ctx, message_id, priority)

    @mcp.tool()
    async def set_message_flag(
        ctx: Context,
        message_id: str,
        status: str,
        due_date: str | None = None,
        start_date: str | None = None,
        time_zone: str = "UTC",
    ) -> str:
        """Set the Outlook follow-up flag and optional reminder on a message.

        ``status``: ``FLAGGED``, ``COMPLETE`` (Outlook "mark as complete"), or ``NOTFLAGGED``
        (clear the flag). ``COMPLETE`` keeps a record of finished follow-up; ``NOTFLAGGED``
        erases the flag — they are not interchangeable.

        Dates accept ``YYYY-MM-DD`` (widened to 17:00, so a due date is not instantly overdue)
        or ``YYYY-MM-DDTHH:MM:SS``. ``time_zone`` defaults to UTC — pass the user's zone to
        avoid a due date landing hours off. Graph requires a start date whenever a due date is
        given; it defaults to the due date.

        Outlook's follow-up reminder is driven by the flag's due date; Graph messages have no
        separate reminder field (that belongs to calendar events).

        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite.
        """
        return await email_writer.set_message_flag(
            ctx,
            message_id,
            status,
            due_date=due_date,
            start_date=start_date,
            time_zone=time_zone,
        )

    @mcp.tool()
    async def move_email(ctx: Context, message_id: str, destination_folder_id: str, compact: bool = True) -> str:
        """Move a message to a different mail folder (requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite).

        ``destination_folder_id`` accepts a folder id (from ``list_folders``), a well-known name
        (``archive``, ``deleteditems``, ``junkemail``, ...), a display name (unique, case-insensitive)
        or a path such as ``"Auto/DMARC"``.

        ``compact`` (default true) returns only ``{ok, new_id, parent_folder_id, subject}`` —
        moving changes the message id, so keep ``new_id``. ``compact=false`` returns the whole
        moved message including its body (tens of thousands of characters). For more than a
        couple of messages use ``move_emails``.
        """
        return await email_writer.move_email(ctx, message_id, destination_folder_id, compact=compact)

    @mcp.tool()
    async def move_emails(ctx: Context, message_ids: list[str], destination_folder_id: str) -> str:
        """Move many messages to one folder in a few Graph ``$batch`` calls (requires ENABLE_WRITE_OPERATIONS=true).

        Up to 1000 ids per call; sent 20 per batch with throttling-aware retries (429 /
        MailboxConcurrency honour ``Retry-After``). ``destination_folder_id`` accepts the same forms
        as ``move_email`` (id, well-known name, display name, ``"Parent/Child"`` path).

        Returns ``{"ok", "destination_folder_id", "summary": {total, succeeded, failed},
        "results": [{old_id, new_id, status, error}]}`` — never message bodies. ``ok`` is false
        if any message failed; retry just the failed ``old_id`` values.
        """
        return await email_writer.move_emails(ctx, message_ids, destination_folder_id)

    @mcp.tool()
    async def set_messages_categories(ctx: Context, items: list[dict[str, Any]]) -> str:
        """Set categories on many messages in Graph ``$batch`` calls (requires ENABLE_WRITE_OPERATIONS=true).

        ``items``: ``[{"message_id": "...", "categories": ["DMARC", "Auto"]}, ...]`` (up to 1000).
        Each item *replaces* that message's categories. Returns ``{"ok", "summary",
        "results": [{message_id, status, error}]}``.
        """
        return await email_writer.set_messages_categories(ctx, items)

    @mcp.tool()
    async def list_message_rules(ctx: Context) -> str:
        """List Inbox rules: id, displayName, sequence, isEnabled, conditions, actions, exceptions.

        Requires delegated ``MailboxSettings.Read`` (or ``MailboxSettings.ReadWrite``).
        """
        return await mailbox_settings.list_message_rules(ctx)

    @mcp.tool()
    async def create_message_rule(
        ctx: Context,
        display_name: str,
        sequence: int,
        conditions: dict[str, Any],
        actions: dict[str, Any],
        exceptions: dict[str, Any] | None = None,
        is_enabled: bool = True,
    ) -> str:
        """Create an Inbox rule (Graph ``messageRule``). Requires ENABLE_WRITE_OPERATIONS=true and
        delegated ``MailboxSettings.ReadWrite`` (add it to GRAPH_OAUTH_SCOPES).

        ``sequence``: execution order, lower runs first (>= 1).

        ``conditions`` / ``exceptions`` — ``messageRulePredicates``. Common keys:
        ``senderContains``, ``subjectContains``, ``bodyContains``, ``bodyOrSubjectContains``,
        ``headerContains``, ``recipientContains`` (each a string or list of strings — all matched
        as substrings); ``fromAddresses`` / ``sentToAddresses`` (list of plain email strings is
        fine, converted to Graph recipients); booleans such as ``sentToMe``, ``sentOnlyToMe``,
        ``sentCcMe``, ``hasAttachments``, ``isAutomaticReply``; ``importance`` (``low``/``normal``/``high``).
        Unknown keys are rejected before calling Graph.

        ``actions`` — ``messageRuleActions``: ``moveToFolder`` / ``copyToFolder`` (folder id,
        well-known name, display name, or path like ``"Auto/DMARC"``), ``assignCategories``
        (list of master category names), ``markAsRead``, ``markImportance``, ``delete``,
        ``stopProcessingRules``, ``forwardTo`` / ``redirectTo`` (email strings).

        Example — DMARC reports into a folder, stop further rules::

            display_name="DMARC reports", sequence=1,
            conditions={"subjectContains": ["Report domain:"]},
            actions={"moveToFolder": "Auto/DMARC", "assignCategories": ["DMARC"],
                     "markAsRead": true, "stopProcessingRules": true}

        Graph validation errors come back as ``graph_code`` / ``graph_message``.
        """
        return await mailbox_settings.create_message_rule(
            ctx,
            display_name=display_name,
            sequence=sequence,
            conditions=conditions,
            actions=actions,
            exceptions=exceptions,
            is_enabled=is_enabled,
        )

    @mcp.tool()
    async def update_message_rule(
        ctx: Context,
        rule_id: str,
        display_name: str | None = None,
        sequence: int | None = None,
        conditions: dict[str, Any] | None = None,
        actions: dict[str, Any] | None = None,
        exceptions: dict[str, Any] | None = None,
        is_enabled: bool | None = None,
    ) -> str:
        """Update an Inbox rule (PATCH). Only the fields you pass change — e.g. ``is_enabled=false``
        to switch a rule off, or a new ``sequence``. Passing ``conditions`` / ``actions`` /
        ``exceptions`` replaces that whole object (same shapes as ``create_message_rule``).
        Requires ENABLE_WRITE_OPERATIONS=true and ``MailboxSettings.ReadWrite``.
        """
        return await mailbox_settings.update_message_rule(
            ctx,
            rule_id,
            display_name=display_name,
            sequence=sequence,
            conditions=conditions,
            actions=actions,
            exceptions=exceptions,
            is_enabled=is_enabled,
        )

    @mcp.tool()
    async def delete_message_rule(ctx: Context, rule_id: str) -> str:
        """Delete an Inbox rule by id (from ``list_message_rules``). Requires ENABLE_WRITE_OPERATIONS=true
        and ``MailboxSettings.ReadWrite``.
        """
        return await mailbox_settings.delete_message_rule(ctx, rule_id)

    @mcp.tool()
    async def create_master_category(ctx: Context, display_name: str, color: str = "preset0") -> str:
        """Create an Outlook master category. Requires ENABLE_WRITE_OPERATIONS=true and
        ``MailboxSettings.ReadWrite``.

        ``display_name`` must be unique and **cannot be renamed later through Graph** (only the
        color is mutable) — to rename, create a new category and delete the old one.

        ``color``: ``preset0``..``preset24``, ``none``, or the color name below (case-insensitive):

        | preset | color | preset | color |
        |---|---|---|---|
        | preset0 | Red | preset13 | DarkGray |
        | preset1 | Orange | preset14 | Black |
        | preset2 | Brown | preset15 | DarkRed |
        | preset3 | Yellow | preset16 | DarkOrange |
        | preset4 | Green | preset17 | DarkBrown |
        | preset5 | Teal | preset18 | DarkYellow |
        | preset6 | Olive | preset19 | DarkGreen |
        | preset7 | Blue | preset20 | DarkTeal |
        | preset8 | Purple | preset21 | DarkOlive |
        | preset9 | Cranberry | preset22 | DarkBlue |
        | preset10 | Steel | preset23 | DarkPurple |
        | preset11 | DarkSteel | preset24 | DarkCranberry |
        | preset12 | Gray | | |
        """
        return await mailbox_settings.create_master_category(ctx, display_name, color=color)

    @mcp.tool()
    async def delete_master_category(ctx: Context, category_id: str) -> str:
        """Delete an Outlook master category by id (from ``list_master_categories``). Messages keep the
        category name string; it just loses its color. Requires ENABLE_WRITE_OPERATIONS=true and
        ``MailboxSettings.ReadWrite``.
        """
        return await mailbox_settings.delete_master_category(ctx, category_id)

    @mcp.tool()
    async def create_mail_folder(
        ctx: Context,
        display_name: str,
        parent_folder_id: str | None = None,
        parent_folder_name: str | None = None,
    ) -> str:
        """Create a mail folder at the mailbox root, or a subfolder under a parent folder.

        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite.

        Parent (for a subfolder): ``parent_folder_id`` (Graph id or well-known name), or
        ``parent_folder_name`` (display name, resolved like ``list_inbox`` ``folder_name``).
        Do not set both parent fields.
        """
        return await email_writer.create_mail_folder(
            ctx,
            display_name,
            parent_folder_id=parent_folder_id,
            parent_folder_name=parent_folder_name,
        )

    @mcp.tool()
    async def create_reply_draft(
        ctx: Context,
        message_id: str,
        comment: str | None = None,
        content_type: str = "Text",
        attachments: list[dict] | None = None,
    ) -> str:
        """Create a reply draft for a message (sender, RE: subject and quoted body pre-filled).

        ``comment`` pre-fills the reply text. ``content_type``: ``Text`` (default) or ``HTML``
        to send ``comment`` as markup, matching ``create_draft`` / ``send_email``. The quoted
        original is preserved in both cases. Optional ``attachments``: same shape as
        ``create_draft``.

        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite.
        """
        return await email_writer.create_reply_draft(
            ctx, message_id, comment=comment, content_type=content_type, attachments=attachments
        )

    @mcp.tool()
    async def list_folders(ctx: Context, top: int = 100) -> str:
        """List mail folders for the signed-in user (id, displayName, item counts).

        Use folder ``id`` values with ``list_inbox`` (``folder_id``) and ``move_email``,
        or as ``parent_folder_id`` / ``parent_folder_name`` for ``create_mail_folder``.
        """
        return await email_reader.list_folders(ctx, top=top)

    return mcp


# Singleton used by console script and tests
mcp_app = build_mcp()


def main() -> None:
    s = get_settings()
    transport = s.mcp_transport.strip().lower().replace("_", "-")
    if transport in ("http", "streamablehttp"):
        transport = "streamable-http"
    if transport not in ("stdio", "streamable-http", "sse"):
        msg = f"Unknown MCP_TRANSPORT: {s.mcp_transport}"
        raise SystemExit(msg)
    if transport == "stdio":
        print(
            "outlook-mcp: stdio transport active — waiting for MCP JSON-RPC on stdin/stdout "
            "(spawn from Cursor, MCP Inspector, or another client; Ctrl+C exits).",
            file=sys.stderr,
        )
        mcp_app.run(transport="stdio")
    elif transport == "sse":
        # ``run_sse_async`` takes no ``stateless_http`` — SSE is inherently stateful.
        mcp_app.run(transport="sse", host=s.mcp_host, port=s.mcp_port)
    else:
        mcp_app.run(
            transport="streamable-http",
            host=s.mcp_host,
            port=s.mcp_port,
            stateless_http=s.mcp_stateless_http,
        )


if __name__ == "__main__":
    main()
