"""Outlook MCP server entrypoint (stdio + streamable-http)."""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from outlook_mcp.config import get_settings
from outlook_mcp.tools import email_classifier, email_extractor, email_reader, email_writer


def build_mcp() -> FastMCP:
    s = get_settings()
    mcp = FastMCP(
        name="outlook-mcp",
        instructions=(
            "Microsoft Outlook / Graph mail tools for AR Email Management. "
            "Pass the user's delegated Graph token via the X-Graph-Token HTTP header "
            "(Streamable HTTP) or rely on GRAPH_DEV_TOKEN / Azure client credentials for development."
        ),
        host=s.mcp_host,
        port=s.mcp_port,
        stateless_http=s.mcp_stateless_http,
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "ok", "service": "outlook-mcp"})

    @mcp.tool()
    async def get_email(message_id: str, ctx: Context) -> str:
        """Fetch one message by Graph message id."""
        return await email_reader.get_email(message_id, ctx)

    @mcp.tool()
    async def get_thread(conversation_id: str, ctx: Context, top: int = 50) -> str:
        """Fetch messages sharing the same conversationId (thread)."""
        return await email_reader.get_thread(conversation_id, ctx, top=top)

    @mcp.tool()
    async def search_emails(query: str, ctx: Context, top: int = 25) -> str:
        """Search mailbox with KQL (Graph $search + ConsistencyLevel: eventual)."""
        return await email_reader.search_emails(query, ctx, top=top)

    @mcp.tool()
    async def list_inbox(ctx: Context, top: int = 25, skip: int = 0) -> str:
        """List recent Inbox messages."""
        return await email_reader.list_inbox(ctx, top=top, skip=skip)

    @mcp.tool()
    async def get_attachments(message_id: str, ctx: Context) -> str:
        """List attachment metadata for a message."""
        return await email_reader.get_attachments(message_id, ctx)

    @mcp.tool()
    async def categorize_email(message_id: str, ctx: Context) -> str:
        """Classify email via MCP sampling (falls back to raw email if sampling unavailable)."""
        return await email_classifier.categorize_email(message_id, ctx)

    @mcp.tool()
    async def extract_email_data(message_id: str, ctx: Context) -> str:
        """Extract structured fields via MCP sampling (falls back if sampling unavailable)."""
        return await email_extractor.extract_email_data(message_id, ctx)

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
        mcp_app.run(transport="stdio")
    elif transport == "sse":
        mcp_app.run(transport="sse")
    else:
        mcp_app.run(transport="streamable-http")


if __name__ == "__main__":
    main()
