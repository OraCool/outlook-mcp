"""Tests for email write tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from outlook_mcp.auth.token_handler import GraphTokenMissingError
from outlook_mcp.tools.email_writer import create_draft, send_email


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
