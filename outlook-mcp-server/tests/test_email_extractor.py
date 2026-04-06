"""Tests for extract_email_data."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.auth.token_handler import GraphTokenMissingError
from outlook_mcp.tools._email_prompt import BEGIN_UNTRUSTED_EMAIL_JSON
from outlook_mcp.tools.email_extractor import EXTRACTION_SYSTEM, extract_email_data

_RAW_MESSAGE = {
    "id": "msg-abc",
    "subject": "Invoice INV-2024-001",
    "bodyPreview": "Please find attached invoice",
    "body": {"contentType": "text", "content": "Amount: $500. Due: 2024-03-01."},
    "receivedDateTime": "2024-02-15T10:00:00Z",
    "from": {"emailAddress": {"address": "vendor@example.com", "name": "Vendor"}},
    "conversationId": "conv-1",
    "toRecipients": [],
    "sentDateTime": None,
    "internetMessageId": None,
    "isRead": False,
    "hasAttachments": False,
    "categories": [],
}

_VALID_EXTRACTION_JSON = json.dumps(
    {
        "email_id": "msg-abc",
        "invoice_numbers": ["INV-2024-001"],
        "amounts": ["$500"],
        "dates": ["2024-03-01"],
        "payment_reference": None,
        "raw_notes": "Invoice for $500 due 2024-03-01",
    }
)


def _make_ctx(sampling_text: str) -> MagicMock:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = sampling_text
    sampling_result.model = "test-model"

    session = MagicMock()
    session.create_message = AsyncMock(return_value=sampling_result)

    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_extract_email_data_success() -> None:
    ctx = _make_ctx(_VALID_EXTRACTION_JSON)
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_RAW_MESSAGE)

    with patch("outlook_mcp.tools.email_extractor.make_graph_client", return_value=mock_client):
        result = await extract_email_data("msg-abc", ctx)

    data = json.loads(result)
    assert data["sampling"] is True
    assert data["model"] == "test-model"
    assert data["extraction"]["email_id"] == "msg-abc"
    assert "INV-2024-001" in data["extraction"]["invoice_numbers"]
    assert data["email"]["id"] == "msg-abc"

    kwargs = ctx.session.create_message.await_args.kwargs
    assert kwargs.get("system_prompt") == EXTRACTION_SYSTEM
    assert BEGIN_UNTRUSTED_EMAIL_JSON in kwargs["messages"][0].content.text


@pytest.mark.asyncio
async def test_extract_email_data_token_missing() -> None:
    ctx = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()
    with patch(
        "outlook_mcp.tools.email_extractor.make_graph_client",
        side_effect=GraphTokenMissingError("no token"),
    ):
        result = await extract_email_data("msg-abc", ctx)
    data = json.loads(result)
    assert data["error"] == "missing_token"


@pytest.mark.asyncio
async def test_extract_email_data_fetch_failure() -> None:
    ctx = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(side_effect=RuntimeError("Connection refused"))

    with patch("outlook_mcp.tools.email_extractor.make_graph_client", return_value=mock_client):
        result = await extract_email_data("msg-abc", ctx)

    data = json.loads(result)
    assert data["error"] == "fetch_failed"
    assert "Connection refused" in data["message"]


@pytest.mark.asyncio
async def test_extract_email_data_sampling_fallback_on_invalid_json() -> None:
    ctx = _make_ctx("Not JSON at all")
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_RAW_MESSAGE)

    with patch("outlook_mcp.tools.email_extractor.make_graph_client", return_value=mock_client):
        result = await extract_email_data("msg-abc", ctx)

    data = json.loads(result)
    assert data["sampling"] is False
    assert "sampling_error" in data
    assert "email" in data


@pytest.mark.asyncio
async def test_extract_email_data_email_id_mismatch() -> None:
    wrong_id_json = _VALID_EXTRACTION_JSON.replace('"msg-abc"', '"msg-other"', 1)
    ctx = _make_ctx(wrong_id_json)
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_RAW_MESSAGE)

    with patch("outlook_mcp.tools.email_extractor.make_graph_client", return_value=mock_client):
        result = await extract_email_data("msg-abc", ctx)

    data = json.loads(result)
    assert data["sampling"] is False
    assert "sampling_error" in data


@pytest.mark.asyncio
async def test_extract_email_data_fenced_json_sampling() -> None:
    fenced = f"```json\n{_VALID_EXTRACTION_JSON}\n```"
    ctx = _make_ctx(fenced)
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_RAW_MESSAGE)

    with patch("outlook_mcp.tools.email_extractor.make_graph_client", return_value=mock_client):
        result = await extract_email_data("msg-abc", ctx)

    data = json.loads(result)
    assert data["sampling"] is True
    assert data["extraction"]["email_id"] == "msg-abc"
