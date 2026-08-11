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
    send_draft_email,
    set_email_priority,
    set_message_categories,
)

_SMALL_ATTACHMENT = {"filename": "a.txt", "content_type": "text/plain", "content_base64": "aGVsbG8="}


class _SettingsDisabled:
    enable_write_operations = False
    max_attachment_count = 10
    max_attachment_upload_bytes = 150 * 1024 * 1024


class _SettingsEnabled:
    enable_write_operations = True
    max_attachment_count = 10
    max_attachment_upload_bytes = 150 * 1024 * 1024


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
async def test_send_draft_email_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await send_draft_email(ctx=None, draft_id="draft-1")
    data = json.loads(result)
    assert data["error"] == "write_disabled"
    assert "ENABLE_WRITE_OPERATIONS" in data["message"]


@pytest.mark.asyncio
async def test_send_draft_email_success() -> None:
    mock_client = AsyncMock()
    mock_client.send_draft = AsyncMock(return_value=None)
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await send_draft_email(ctx=None, draft_id="draft-123")
    data = json.loads(result)
    assert data["ok"] is True
    assert data["draft_id"] == "draft-123"
    mock_client.send_draft.assert_awaited_once_with("draft-123")


@pytest.mark.asyncio
async def test_send_draft_email_token_missing() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch(
            "outlook_mcp.tools.email_writer.make_graph_client",
            side_effect=GraphTokenMissingError("no token"),
        ):
            result = await send_draft_email(ctx=None, draft_id="draft-123")
    data = json.loads(result)
    assert data["error"] == "missing_token"


@pytest.mark.asyncio
async def test_send_draft_email_http_error() -> None:
    mock_client = AsyncMock()
    mock_response = AsyncMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    mock_client.send_draft = AsyncMock(
        side_effect=httpx.HTTPStatusError("403", request=AsyncMock(), response=mock_response)
    )
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await send_draft_email(ctx=None, draft_id="draft-123")
    data = json.loads(result)
    assert data["error"] == "http_error"
    assert data["status_code"] == 403


@pytest.mark.asyncio
async def test_send_draft_email_network_error_sanitized() -> None:
    mock_client = AsyncMock()
    mock_client.send_draft = AsyncMock(
        side_effect=httpx.ConnectError("failed contact@evil.com", request=MagicMock()),
    )
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await send_draft_email(ctx=None, draft_id="draft-123")
    data = json.loads(result)
    assert data["error"] == "network_error"
    assert "[EMAIL_REDACTED]" in data["message"]


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
async def test_set_email_priority_write_disabled() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()):
        result = await set_email_priority(ctx=None, message_id="m1", priority="HIGH")
    data = json.loads(result)
    assert data["error"] == "write_disabled"


@pytest.mark.asyncio
async def test_set_email_priority_validation() -> None:
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        result = await set_email_priority(ctx=None, message_id="m1", priority="URGENT")
    data = json.loads(result)
    assert data["error"] == "validation_error"


@pytest.mark.asyncio
async def test_set_email_priority_success() -> None:
    mock_client = AsyncMock()
    mock_client.update_message = AsyncMock(return_value={})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await set_email_priority(ctx=None, message_id="mid-1", priority="medium")
    data = json.loads(result)
    assert data["ok"] is True
    assert data["importance"] == "normal"
    mock_client.update_message.assert_awaited_once_with("mid-1", {"importance": "normal"})


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
    mock_client.create_reply.assert_awaited_once_with("orig", comment="Hi", content_type="Text")


@pytest.mark.asyncio
async def test_create_reply_draft_without_comment() -> None:
    mock_client = AsyncMock()
    mock_client.create_reply = AsyncMock(return_value={"id": "draft-2"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            result = await create_reply_draft(ctx=None, message_id="orig", comment=None)
    data = json.loads(result)
    assert data["ok"] is True
    mock_client.create_reply.assert_awaited_once_with("orig", comment=None, content_type="Text")


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


@pytest.mark.asyncio
async def test_create_reply_draft_passes_html_content_type() -> None:
    """HTML replies must reach the Graph client; the plain-text default stays unchanged."""
    mock_client = AsyncMock()
    mock_client.create_reply = AsyncMock(return_value={"id": "draft-1"})
    with (
        patch("outlook_mcp.tools.email_writer.get_settings") as gs,
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        gs.return_value = MagicMock(enable_write_operations=True)
        out = json.loads(
            await create_reply_draft(MagicMock(log=AsyncMock(), report_progress=AsyncMock()),
                                     "orig", comment="<b>Hi</b>", content_type="HTML")
        )
    assert out["ok"] is True
    mock_client.create_reply.assert_awaited_once_with("orig", comment="<b>Hi</b>", content_type="HTML")


@pytest.mark.asyncio
async def test_graph_client_html_reply_preserves_the_quoted_original() -> None:
    """Graph drops the quote if message.body is passed to createReply (v1.0 and beta alike),
    so the HTML path must create the reply first and PATCH our markup in front of the quote."""
    from outlook_mcp.auth.graph_client import GraphMailClient

    quoted = "<div>-----Original Message-----<br>lots of quoted text</div>"
    posted = MagicMock(status_code=201)
    posted.json = MagicMock(return_value={"id": "draft-1", "body": {"content": quoted}})
    posted.raise_for_status = MagicMock()
    patched = MagicMock(status_code=200, content=b"{}")
    patched.json = MagicMock(return_value={"id": "draft-1"})
    patched.raise_for_status = MagicMock()

    http = MagicMock()
    http.post = AsyncMock(return_value=posted)
    http.patch = AsyncMock(return_value=patched)
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)

    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        await client.create_reply("orig", comment="<p>Hi</p>", content_type="HTML")

    # createReply must be called WITHOUT message.body, or the quote is lost.
    assert http.post.await_args.kwargs.get("json") is None
    sent = http.patch.await_args.kwargs["json"]["body"]
    assert sent["contentType"] == "HTML"
    assert sent["content"] == "<p>Hi</p>" + quoted


@pytest.mark.asyncio
async def test_send_email_with_small_attachment_inline() -> None:
    mock_client = AsyncMock()
    mock_client.send_mail = AsyncMock(return_value=None)
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await send_email(
            ctx=None,
            subject="S",
            body_text="B",
            to_addresses=["a@b.com"],
            attachments=[_SMALL_ATTACHMENT],
        )
    data = json.loads(result)
    assert data["ok"] is True
    payload = mock_client.send_mail.call_args[0][0]
    assert payload["message"]["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "a.txt",
            "contentType": "text/plain",
            "contentBytes": "aGVsbG8=",
            "isInline": False,
        }
    ]
    mock_client.create_message_draft.assert_not_awaited()
    mock_client.send_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_email_with_large_attachment_uses_draft_path() -> None:
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value={"id": "draft-1"})
    mock_client.upload_large_attachment = AsyncMock(return_value={"id": "att-1", "name": "a.txt"})
    mock_client.send_draft = AsyncMock(return_value=None)
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
        patch("outlook_mcp.tools._attachments.SMALL_ATTACHMENT_THRESHOLD_BYTES", 1),
    ):
        result = await send_email(
            ctx=None,
            subject="S",
            body_text="B",
            to_addresses=["a@b.com"],
            attachments=[_SMALL_ATTACHMENT],
        )
    data = json.loads(result)
    assert data["ok"] is True
    assert data["used_draft_path"] is True
    mock_client.create_message_draft.assert_awaited_once()
    mock_client.upload_large_attachment.assert_awaited_once()
    mock_client.send_draft.assert_awaited_once_with("draft-1")
    mock_client.send_mail.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_email_attachment_oversized_rejected() -> None:
    class _SettingsTinyLimit(_SettingsEnabled):
        max_attachment_upload_bytes = 1

    mock_client = AsyncMock()
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsTinyLimit()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await send_email(
            ctx=None, subject="S", body_text="B", to_addresses=["a@b.com"], attachments=[_SMALL_ATTACHMENT]
        )
    data = json.loads(result)
    assert data["error"] == "validation_error"
    mock_client.send_mail.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_email_attachment_count_exceeded() -> None:
    class _SettingsTinyCount(_SettingsEnabled):
        max_attachment_count = 1

    mock_client = AsyncMock()
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsTinyCount()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await send_email(
            ctx=None,
            subject="S",
            body_text="B",
            to_addresses=["a@b.com"],
            attachments=[_SMALL_ATTACHMENT, _SMALL_ATTACHMENT],
        )
    data = json.loads(result)
    assert data["error"] == "validation_error"
    mock_client.send_mail.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_email_attachment_bad_base64() -> None:
    mock_client = AsyncMock()
    bad = {"filename": "a.txt", "content_base64": "not-valid-base64!!"}
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await send_email(
            ctx=None, subject="S", body_text="B", to_addresses=["a@b.com"], attachments=[bad]
        )
    data = json.loads(result)
    assert data["error"] == "validation_error"
    mock_client.send_mail.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_draft_with_attachment_small() -> None:
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value={"id": "draft-1"})
    mock_client.add_attachment_small = AsyncMock(
        return_value={"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}
    )
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await create_draft(ctx=None, subject="S", body_text="B", attachments=[_SMALL_ATTACHMENT])
    data = json.loads(result)
    assert data["ok"] is True
    assert data["attachments"] == [{"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}]
    mock_client.create_message_draft.assert_awaited_once()
    mock_client.add_attachment_small.assert_awaited_once_with(
        "draft-1", name="a.txt", content_type="text/plain", content_b64="aGVsbG8=", is_inline=False
    )


@pytest.mark.asyncio
async def test_create_draft_with_attachment_large() -> None:
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value={"id": "draft-1"})
    mock_client.upload_large_attachment = AsyncMock(return_value={"id": "att-1", "name": "a.txt"})
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
        patch("outlook_mcp.tools._attachments.SMALL_ATTACHMENT_THRESHOLD_BYTES", 1),
    ):
        result = await create_draft(ctx=None, subject="S", body_text="B", attachments=[_SMALL_ATTACHMENT])
    data = json.loads(result)
    assert data["ok"] is True
    mock_client.upload_large_attachment.assert_awaited_once()
    mock_client.add_attachment_small.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_reply_draft_with_attachment() -> None:
    mock_client = AsyncMock()
    mock_client.create_reply = AsyncMock(return_value={"id": "draft-1"})
    mock_client.add_attachment_small = AsyncMock(
        return_value={"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}
    )
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await create_reply_draft(ctx=None, message_id="orig", attachments=[_SMALL_ATTACHMENT])
    data = json.loads(result)
    assert data["ok"] is True
    assert data["attachments"] == [{"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}]
    mock_client.create_reply.assert_awaited_once_with("orig", comment=None, content_type="Text")
    mock_client.add_attachment_small.assert_awaited_once_with(
        "draft-1", name="a.txt", content_type="text/plain", content_b64="aGVsbG8=", is_inline=False
    )


@pytest.mark.asyncio
async def test_create_draft_attachments_write_disabled() -> None:
    mock_client = AsyncMock()
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsDisabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await create_draft(ctx=None, subject="S", body_text="B", attachments=[_SMALL_ATTACHMENT])
    data = json.loads(result)
    assert data["error"] == "write_disabled"
    mock_client.create_message_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_draft_attachment_http_error_surfaces_draft_id() -> None:
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value={"id": "draft-1"})
    resp = MagicMock(status_code=500, text="boom")
    mock_client.add_attachment_small = AsyncMock(side_effect=httpx.HTTPStatusError("boom", request=MagicMock(), response=resp))
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await create_draft(ctx=None, subject="S", body_text="B", attachments=[_SMALL_ATTACHMENT])
    data = json.loads(result)
    assert data["error"] == "http_error"
    assert data["draft_id"] == "draft-1"


@pytest.mark.asyncio
async def test_create_draft_with_file_path_attachment(tmp_path) -> None:
    import base64

    content = b"%PDF-1.4 fake content"
    f = tmp_path / "invoice.pdf"
    f.write_bytes(content)
    mock_client = AsyncMock()
    mock_client.create_message_draft = AsyncMock(return_value={"id": "draft-1"})
    mock_client.add_attachment_small = AsyncMock(
        return_value={"id": "att-1", "name": "invoice.pdf", "size": len(content), "contentType": "application/pdf"}
    )
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await create_draft(
            ctx=None, subject="S", body_text="B", attachments=[{"file_path": str(f)}]
        )
    data = json.loads(result)
    assert data["ok"] is True
    assert data["attachments"] == [
        {"id": "att-1", "name": "invoice.pdf", "size": len(content), "contentType": "application/pdf"}
    ]
    mock_client.add_attachment_small.assert_awaited_once_with(
        "draft-1",
        name="invoice.pdf",
        content_type="application/pdf",
        content_b64=base64.b64encode(content).decode(),
        is_inline=False,
    )


@pytest.mark.asyncio
async def test_send_email_file_path_attachment_missing_file_rejected() -> None:
    mock_client = AsyncMock()
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_SettingsEnabled()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client),
    ):
        result = await send_email(
            ctx=None,
            subject="S",
            body_text="B",
            to_addresses=["a@b.com"],
            attachments=[{"file_path": "/no/such/file.pdf"}],
        )
    data = json.loads(result)
    assert data["error"] == "validation_error"
    mock_client.send_mail.assert_not_awaited()
