"""Outlook MCP server entrypoint (stdio + streamable-http)."""

from __future__ import annotations

import sys

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from outlook_mcp.config import get_settings
from outlook_mcp.tools import email_classifier, email_drafter, email_extractor, email_reader, email_summarizer, email_writer


def build_mcp() -> FastMCP:
    s = get_settings()
    mcp = FastMCP(
        name="outlook-mcp",
        instructions=(
            "Microsoft Outlook / Graph mail tools for AR Email Management. "
            "Auth: X-Graph-Token header; or enable OAuth and use GET /oauth/login then X-OAuth-Session; "
            "or GRAPH_OAUTH_TOKEN_CACHE_PATH after outlook-mcp-oauth-device; or GRAPH_DEV_TOKEN for local dev. "
            "search_emails: the query parameter is KQL (Keyword Query Language) against the signed-in user's mailbox; "
            "Graph uses eventual consistency for this API. Reference: "
            "https://learn.microsoft.com/en-us/graph/search-query-parameter"
        ),
        host=s.mcp_host,
        port=s.mcp_port,
        stateless_http=s.mcp_stateless_http,
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
        """List attachment metadata for a message."""
        return await email_reader.get_attachments(message_id, ctx)

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
    ) -> str:
        """Send email (requires ENABLE_WRITE_OPERATIONS=true and Mail.Send)."""
        return await email_writer.send_email(
            ctx,
            subject=subject,
            body_text=body_text,
            to_addresses=to_addresses,
            content_type=content_type,
            save_to_sent_items=save_to_sent_items,
        )

    @mcp.tool()
    async def create_draft(
        ctx: Context,
        subject: str,
        body_text: str,
        to_addresses: list[str] | None = None,
        content_type: str = "Text",
    ) -> str:
        """Create a draft message (requires ENABLE_WRITE_OPERATIONS=true)."""
        return await email_writer.create_draft(
            ctx,
            subject=subject,
            body_text=body_text,
            to_addresses=to_addresses,
            content_type=content_type,
        )

    @mcp.tool()
    async def mark_as_read(ctx: Context, message_id: str, is_read: bool = True) -> str:
        """Mark a message as read or unread (requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite)."""
        return await email_writer.mark_as_read(ctx, message_id, is_read=is_read)

    @mcp.tool()
    async def set_email_priority(ctx: Context, message_id: str, priority: str) -> str:
        """Set Outlook message importance: HIGH, MEDIUM, or LOW (Graph high/normal/low).

        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite. Distinct from classifier
        priority on ``categorize_email``.
        """
        return await email_writer.set_email_priority(ctx, message_id, priority)

    @mcp.tool()
    async def move_email(ctx: Context, message_id: str, destination_folder_id: str) -> str:
        """Move a message to a different mail folder (requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite).

        Use ``list_folders`` to discover folder IDs.
        """
        return await email_writer.move_email(ctx, message_id, destination_folder_id)

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
    async def create_reply_draft(ctx: Context, message_id: str, comment: str | None = None) -> str:
        """Create a reply draft for a message, pre-populated with sender, subject (RE:), and quoted body.

        Optionally include ``comment`` to pre-fill the reply body text.
        Requires ENABLE_WRITE_OPERATIONS=true and Mail.ReadWrite.
        """
        return await email_writer.create_reply_draft(ctx, message_id, comment=comment)

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
        mcp_app.run(transport="sse")
    else:
        mcp_app.run(transport="streamable-http")


if __name__ == "__main__":
    main()
