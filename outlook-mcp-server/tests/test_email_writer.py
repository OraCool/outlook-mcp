"""Tests for email write tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from outlook_mcp.auth.token_handler import GraphTokenMissingError
from outlook_mcp.tools.email_writer import (
    create_draft,
    create_mail_folder,
    create_reply_draft,
    mark_as_read,
    move_email,
    send_email,
    set_message_categories,
)


class _SettingsDisabled:
    enable_write_operations = False


class _SettingsEnabled:
    enable_write_operations = True


@pytest.mark.asyncio
async def test_send_email_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await send_email(ctx=None, subject="S", body_text="B", to_addresses=["a@b.com"])
    data = json.loads(result)
    assert data["error"] == "write_disabled"
    assert "ENABLE_WRITE_OPERATIONS" in data["message"]


@pytest.mark.asyncio
async def test_create_draft_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await create_draft(ctx=None, subject="S", body_text="B")
    data = json.loads(result)
    assert data["error"] == "write_disabled"
    assert "ENABLE_WRITE_OPERATIONS" in data["message"]


@pytest.mark.asyncio
async def test_send_email_success() -> None:
    mock_client = AsyncMock()
    mock_client.send_mail = AsyncMock(return_value=None)
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await send_email(
                ctx=None,
                subject="Invoice #42",
                body_text="Please pay.",
                to_addresses=["vendor@example.com"],
                save_to_sent_items=False,
            )
    data = json.loads(result)
    assert data["ok"] is True
    payload = mock_client.send_mail.call_args[0][0]
    assert payload["message"]["subject"] == "Invoice #42"
    assert payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "vendor@example.com"
    assert payload["saveToSentItems"] is False


@pytest.mark.asyncio
async def test_send_email_multiple_recipients() -> None:
    mock_client = AsyncMock()
    mock_client.send_mail = AsyncMock(return_value=None)
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            await send_email(
                ctx=None,
                subject="S",
                body_text="B",
                to_addresses=["a@b.com", "c@d.com"],
            )
    payload = mock_client.send_mail.call_args[0][0]
    assert len(payload["message"]["toRecipients"]) == 2


@pytest.mark.asyncio
async def test_create_draft_success() -> None:
    draft_resp = {"id": "draft-123", "subject": "My Draft"}
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value=draft_resp)
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_draft(
                ctx=None,
                subject="My Draft",
                body_text="Draft body",
                to_addresses=["a@b.com"],
            )
    data = json.loads(result)
    assert data["ok"] is True
    assert data["message"]["id"] == "draft-123"
    msg_payload = mock_client.create_message_draft.call_args[0][0]
    assert msg_payload["toRecipients"][0]["emailAddress"]["address"] == "a@b.com"


@pytest.mark.asyncio
async def test_create_draft_no_recipients() -> None:
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value={"id": "draft-456"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            await create_draft(ctx=None, subject="No To", body_text="B")
    msg_payload = mock_client.create_message_draft.call_args[0][0]
    assert "toRecipients" not in msg_payload


@pytest.mark.asyncio
async def test_send_email_token_missing() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch(
            "outlook_mcp.tools.email_writer.make_graph_client",
            side_effect=GraphTokenMissingError("no token"),
        ):
            result = await send_email(ctx=None, subject="S", body_text="B", to_addresses=["a@b.com"])
    data = json.loads(result)
    assert data["error"] == "missing_token"


@pytest.mark.asyncio
async def test_set_message_categories_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await set_message_categories(ctx=None, message_id="m1", categories=["A"])
    data = json.loads(result)
    assert data["error"] == "write_disabled"


@pytest.mark.asyncio
async def test_set_message_categories_validation_empty() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        result = await set_message_categories(ctx=None, message_id="m1", categories=[])
    data = json.loads(result)
    assert data["error"] == "validation_error"


@pytest.mark.asyncio
async def test_set_message_categories_success() -> None:
    mock_client = AsyncMock()
    mock_client.update_message = AsyncMock(return_value={})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await set_message_categories(ctx=None, message_id="mid-1", categories=["  PAYMENT_PROMISE  "])
    data = json.loads(result)
    assert data["ok"] is True
    assert data["categories"] == ["PAYMENT_PROMISE"]
    mock_client.update_message.assert_awaited_once_with(
        "mid-1",
        {"categories": ["PAYMENT_PROMISE"]},
    )


@pytest.mark.asyncio
async def test_send_email_http_error() -> None:
    mock_client = AsyncMock()
    mock_response = AsyncMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    mock_client.send_mail = AsyncMock(
        side_effect=httpx.HTTPStatusError("403", request=AsyncMock(), response=mock_response)
    )
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await send_email(ctx=None, subject="S", body_text="B", to_addresses=["a@b.com"])
    data = json.loads(result)
    assert data["error"] == "http_error"
    assert data["status_code"] == 403


@pytest.mark.asyncio
async def test_mark_as_read_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await mark_as_read(ctx=None, message_id="m1", is_read=True)
    data = json.loads(result)
    assert data["error"] == "write_disabled"


@pytest.mark.asyncio
async def test_mark_as_read_success() -> None:
    mock_client = AsyncMock()
    mock_client.update_message = AsyncMock(return_value={})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await mark_as_read(ctx=None, message_id="mid-1", is_read=False)
    data = json.loads(result)
    assert data["ok"] is True
    assert data["is_read"] is False
    mock_client.update_message.assert_awaited_once_with("mid-1", {"isRead": False})


@pytest.mark.asyncio
async def test_mark_as_read_network_error_sanitized() -> None:
    mock_client = AsyncMock()
    mock_client.update_message = AsyncMock(
        side_effect=httpx.ConnectError("failed contact@evil.com", request=MagicMock()),
    )
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await mark_as_read(ctx=None, message_id="mid-1")
    data = json.loads(result)
    assert data["error"] == "network_error"
    assert "[EMAIL_REDACTED]" in data["message"]


@pytest.mark.asyncio
async def test_move_email_success() -> None:
    mock_client = AsyncMock()
    mock_client.move_message = AsyncMock(return_value={"id": "m1", "subject": "S"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await move_email(ctx=None, message_id="m1", destination_folder_id="fid")
    data = json.loads(result)
    assert data["ok"] is True
    mock_client.move_message.assert_awaited_once_with("m1", "fid")


@pytest.mark.asyncio
async def test_move_email_http_error() -> None:
    mock_client = AsyncMock()
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "Bad"
    mock_client.move_message = AsyncMock(
        side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=resp),
    )
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await move_email(ctx=None, message_id="m1", destination_folder_id="fid")
    data = json.loads(result)
    assert data["error"] == "http_error"
    assert data["status_code"] == 400


@pytest.mark.asyncio
async def test_create_reply_draft_success() -> None:
    mock_client = AsyncMock()
    mock_client.create_reply = AsyncMock(return_value={"id": "draft-1"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_reply_draft(ctx=None, message_id="orig", comment="Hi")
    data = json.loads(result)
    assert data["ok"] is True
    mock_client.create_reply.assert_awaited_once_with("orig", comment="Hi")


@pytest.mark.asyncio
async def test_create_reply_draft_without_comment() -> None:
    mock_client = AsyncMock()
    mock_client.create_reply = AsyncMock(return_value={"id": "draft-2"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_reply_draft(ctx=None, message_id="orig", comment=None)
    data = json.loads(result)
    assert data["ok"] is True
    mock_client.create_reply.assert_awaited_once_with("orig", comment=None)


@pytest.mark.asyncio
async def test_create_mail_folder_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await create_mail_folder(ctx=None, display_name="New")
    data = json.loads(result)
    assert data["error"] == "write_disabled"


@pytest.mark.asyncio
async def test_create_mail_folder_success_root() -> None:
    mock_client = AsyncMock()
    mock_client.create_mail_folder = AsyncMock(
        return_value={"id": "fid-1", "displayName": "Projects"},
    )
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_mail_folder(ctx=None, display_name="Projects")
    data = json.loads(result)
    assert data["ok"] is True
    assert data["folder"]["id"] == "fid-1"
    mock_client.create_mail_folder.assert_awaited_once_with(
        "Projects", parent_folder_id=None
    )


@pytest.mark.asyncio
async def test_create_mail_folder_success_subfolder() -> None:
    mock_client = AsyncMock()
    mock_client.create_mail_folder = AsyncMock(return_value={"id": "fid-2"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_mail_folder(
                ctx=None, display_name="Nested", parent_folder_id="parent-id"
            )
    data = json.loads(result)
    assert data["ok"] is True
    mock_client.create_mail_folder.assert_awaited_once_with(
        "Nested", parent_folder_id="parent-id"
    )


@pytest.mark.asyncio
async def test_create_mail_folder_success_subfolder_by_parent_name() -> None:
    mock_client = AsyncMock()
    mock_client.resolve_mail_folder_id_by_display_name = AsyncMock(return_value="resolved-parent")
    mock_client.create_mail_folder = AsyncMock(return_value={"id": "fid-3"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_mail_folder(
                ctx=None,
                display_name="Nested",
                parent_folder_name="Projects",
            )
    data = json.loads(result)
    assert data["ok"] is True
    assert data["resolved_parent_folder_id"] == "resolved-parent"
    assert data["parent_folder_name"] == "Projects"
    mock_client.resolve_mail_folder_id_by_display_name.assert_awaited_once_with("Projects")
    mock_client.create_mail_folder.assert_awaited_once_with(
        "Nested", parent_folder_id="resolved-parent"
    )


@pytest.mark.asyncio
async def test_create_mail_folder_rejects_parent_id_and_name() -> None:
    mock_client = AsyncMock()
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_mail_folder(
                ctx=None,
                display_name="X",
                parent_folder_id="a",
                parent_folder_name="B",
            )
    data = json.loads(result)
    assert data["error"] == "invalid_parameters"
    mock_client.create_mail_folder.assert_not_called()
