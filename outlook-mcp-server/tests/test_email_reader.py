"""Graph client and message mapping."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from urllib.parse import quote

from outlook_mcp.auth.graph_client import GraphMailClient
from outlook_mcp.auth.token_handler import GraphTokenMissingError
from outlook_mcp.tools._common import graph_message_to_model
from outlook_mcp.tools.email_reader import _LIST_SELECT, list_folders, list_inbox, list_master_categories


def test_graph_mail_client_user_prefix_me_and_mailbox() -> None:
    me = GraphMailClient("t")
    assert me._user_prefix() == "/me"
    mb = GraphMailClient("t", mailbox="a@b.com")
    assert mb._user_prefix() == f"/users/{quote('a@b.com', safe='')}"


def test_graph_message_to_model_minimal() -> None:
    raw = {
        "id": "msg-1",
        "subject": "Hello",
        "bodyPreview": "Hi",
        "body": {"contentType": "text", "content": "Hi there"},
        "from": {"emailAddress": {"address": "a@b.com", "name": "A"}},
        "toRecipients": [{"emailAddress": {"address": "c@d.com"}}],
    }
    m = graph_message_to_model(raw)
    assert m.id == "msg-1"
    assert m.subject == "Hello"
    assert m.from_ is not None
    assert m.from_.address == "a@b.com"


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_get_message(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "id": "mid",
            "subject": "S",
            "body": {},
        }
    )

    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.get_message("mid", select="id,subject")
    assert out["id"] == "mid"
    mock_instance.get.assert_awaited()


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_update_message(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b'{"id":"mid"}'
    mock_response.json = MagicMock(return_value={"id": "mid"})
    mock_instance = AsyncMock()
    mock_instance.patch = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.update_message("mid", {"categories": ["UNCLASSIFIED"]})
    assert out["id"] == "mid"
    mock_instance.patch.assert_awaited_once_with(
        "/me/messages/mid",
        json={"categories": ["UNCLASSIFIED"]},
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_update_message_no_content(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b""
    mock_instance = AsyncMock()
    mock_instance.patch = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.update_message("mid", {"categories": ["X"]})
    assert out == {}
    mock_instance.patch.assert_awaited_once_with("/me/messages/mid", json={"categories": ["X"]})


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_encodes_message_id_in_path(mock_async_client_class: MagicMock) -> None:
    """Graph ids may contain ``+``, ``/``, ``=``; they must be percent-encoded in the URL path."""
    raw_id = "A+/=tail"
    enc = quote(raw_id.strip(), safe="")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b""
    mock_instance = AsyncMock()
    mock_instance.patch = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    await gc.update_message(raw_id, {"categories": ["PAYMENT_REMINDER_SENT"]})
    mock_instance.patch.assert_awaited_once_with(
        f"/me/messages/{enc}",
        json={"categories": ["PAYMENT_REMINDER_SENT"]},
    )


def test_list_select_omits_full_body_field() -> None:
    parts = {p.strip() for p in _LIST_SELECT.split(",")}
    assert "body" not in parts
    assert "bodyPreview" in parts


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_list_inbox_passes_select(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"value": []})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    await gc.list_inbox(top=10, skip=2, select=_LIST_SELECT)
    mock_instance.get.assert_awaited_once_with(
        "/me/mailFolders/Inbox/messages",
        params={
            "$top": "10",
            "$skip": "2",
            "$orderby": "receivedDateTime desc",
            "$select": _LIST_SELECT,
        },
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_search_messages_passes_select(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"value": []})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    await gc.search_messages("subject:pay", top=5, select=_LIST_SELECT)
    mock_instance.get.assert_awaited_once_with(
        "/me/messages",
        params={"$search": '"subject:pay"', "$top": "5", "$select": _LIST_SELECT},
        headers={
            "Authorization": "Bearer fake-token",
            "Accept": "application/json",
            "ConsistencyLevel": "eventual",
        },
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_list_by_conversation_passes_select(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"value": []})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    await gc.list_messages_by_conversation("conv-1", top=20, select=_LIST_SELECT)
    mock_instance.get.assert_awaited_once_with(
        "/me/messages",
        params={
            "$filter": "conversationId eq 'conv-1'",
            "$top": "20",
            "$select": _LIST_SELECT,
        },
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_list_by_conversation_sorts_by_received(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "value": [
                {"id": "b", "receivedDateTime": "2026-03-18T10:00:00Z"},
                {"id": "a", "receivedDateTime": "2026-03-17T12:00:00Z"},
            ],
        },
    )
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.list_messages_by_conversation("conv-1", top=10)
    ids = [m["id"] for m in out["value"]]
    assert ids == ["a", "b"]


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_list_master_categories(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "value": [
                {"id": "cat-1", "displayName": "Important", "color": "preset0"},
            ],
        },
    )

    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.list_master_categories()
    assert len(out["value"]) == 1
    assert out["value"][0]["displayName"] == "Important"
    mock_instance.get.assert_awaited_once_with(
        "/me/outlook/masterCategories",
        params={"$top": "500"},
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_list_master_categories_with_top(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"value": []})
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    await gc.list_master_categories(top=25)
    mock_instance.get.assert_awaited_once_with(
        "/me/outlook/masterCategories",
        params={"$top": "25"},
    )


@pytest.mark.asyncio
async def test_list_master_categories_tool_returns_json() -> None:
    ctx = MagicMock()
    mock_client = MagicMock()
    mock_client.list_master_categories = AsyncMock(
        return_value={"value": [{"id": "x", "displayName": "Blue", "color": "preset1"}]},
    )
    with patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=mock_client):
        result = await list_master_categories(ctx)
    data = json.loads(result)
    assert data["count"] == 1
    assert data["categories"][0]["displayName"] == "Blue"


@pytest.mark.asyncio
async def test_list_inbox_missing_token_returns_despite_slow_mcp_notify() -> None:
    """Inspector-style clients may stall on log/progress; tools must still return errors."""

    async def slow_notify(*_a: object, **_k: object) -> None:
        await asyncio.sleep(10.0)

    ctx = MagicMock()
    ctx.log = AsyncMock(side_effect=slow_notify)
    ctx.report_progress = AsyncMock(side_effect=slow_notify)

    with patch(
        "outlook_mcp.tools.email_reader.make_graph_client",
        side_effect=GraphTokenMissingError("no token"),
    ):
        t0 = time.monotonic()
        result = await list_inbox(ctx, top=5, skip=0)
        elapsed = time.monotonic() - t0

    assert elapsed < 1.0, "list_inbox should not block on stalled MCP notifications"
    data = json.loads(result)
    assert data["error"] == "missing_token"


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_move_message(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "moved-1"})
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.move_message("mid-1", "folder-inbox-id")
    assert out["id"] == "moved-1"
    mock_instance.post.assert_awaited_once_with(
        "/me/messages/mid-1/move",
        json={"destinationId": "folder-inbox-id"},
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_create_reply_no_body_when_no_comment(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "draft-1"})
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.create_reply("msg-abc", comment=None)
    assert out["id"] == "draft-1"
    mock_instance.post.assert_awaited_once_with("/me/messages/msg-abc/createReply")


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_create_reply_with_comment(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "draft-2"})
    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    await gc.create_reply("msg-abc", comment="Thanks,")
    mock_instance.post.assert_awaited_once_with(
        "/me/messages/msg-abc/createReply",
        json={"comment": "Thanks,"},
    )


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_list_folders(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "value": [
                {"id": "fid", "displayName": "Inbox", "parentFolderId": None, "totalItemCount": 5},
            ],
        },
    )
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.list_folders(top=100)
    assert len(out["value"]) == 1
    mock_instance.get.assert_awaited_once_with(
        "/me/mailFolders",
        params={"$top": "100"},
    )


@pytest.mark.asyncio
async def test_list_folders_network_error_logs_warning() -> None:
    ctx = MagicMock()
    ctx.log = AsyncMock()

    async def boom(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("no route", request=MagicMock())

    mock_client = MagicMock()
    mock_client.list_folders = AsyncMock(side_effect=boom)

    with patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=mock_client):
        result = await list_folders(ctx, top=10)
    data = json.loads(result)
    assert data["error"] == "network_error"
    ctx.log.assert_awaited()
    # elicitation calls use level "warning" for operational issues
    levels = [c.args[0] for c in ctx.log.call_args_list if c.args]
    assert "warning" in levels
