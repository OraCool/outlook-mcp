"""Read-only Graph mail tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.tools._common import graph_message_to_model, make_graph_client, tool_error_token

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context


_DEFAULT_SELECT = (
    "id,subject,bodyPreview,body,receivedDateTime,sentDateTime,conversationId,"
    "internetMessageId,from,sender,toRecipients,isRead,hasAttachments,categories"
)


async def get_email(message_id: str, ctx: Context) -> str:
    """Fetch a single message by Graph message id (delegated: ``Mail.Read``)."""
    try:
        client = make_graph_client(ctx)
        raw = await client.get_message(message_id, select=_DEFAULT_SELECT)
        model = graph_message_to_model(raw)
        return json.dumps(model.model_dump(mode="json", by_alias=True), indent=2)
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


async def get_thread(conversation_id: str, ctx: Context, top: int = 50) -> str:
    """List messages in a thread by ``conversationId``."""
    try:
        client = make_graph_client(ctx)
        data = await client.list_messages_by_conversation(conversation_id, top=top)
        items = data.get("value") or []
        models = [graph_message_to_model(m).model_dump(mode="json", by_alias=True) for m in items]
        return json.dumps({"conversation_id": conversation_id, "messages": models, "count": len(models)})
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {"error": "http_error", "status_code": e.response.status_code, "message": e.response.text[:2000]}
        )


async def search_emails(query: str, ctx: Context, top: int = 25) -> str:
    """Search the signed-in user's mailbox (KQL). Requires eventual consistency header on Graph."""
    try:
        client = make_graph_client(ctx)
        data = await client.search_messages(query, top=top)
        items = data.get("value") or []
        # Search responses may omit body; enrich minimally
        slim: list[dict[str, Any]] = []
        for m in items:
            slim.append(
                graph_message_to_model(
                    {
                        **m,
                        "body": m.get("body") or {},
                    }
                ).model_dump(mode="json", by_alias=True)
            )
        return json.dumps({"query": query, "messages": slim, "count": len(slim)})
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {"error": "http_error", "status_code": e.response.status_code, "message": e.response.text[:2000]}
        )


async def list_inbox(ctx: Context, top: int = 25, skip: int = 0) -> str:
    """List recent Inbox messages (newest first)."""
    try:
        client = make_graph_client(ctx)
        data = await client.list_inbox(top=top, skip=skip)
        items = data.get("value") or []
        models = [graph_message_to_model(m).model_dump(mode="json", by_alias=True) for m in items]
        return json.dumps({"messages": models, "count": len(models), "top": top, "skip": skip})
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {"error": "http_error", "status_code": e.response.status_code, "message": e.response.text[:2000]}
        )


async def get_attachments(message_id: str, ctx: Context) -> str:
    """List attachments metadata for a message (does not download file bytes)."""
    try:
        client = make_graph_client(ctx)
        data = await client.list_attachments(message_id)
        return json.dumps(data, indent=2)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except httpx.HTTPStatusError as e:
        return json.dumps(
            {"error": "http_error", "status_code": e.response.status_code, "message": e.response.text[:2000]}
        )
