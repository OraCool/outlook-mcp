"""Tests for email_drafter MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.tools.email_drafter import draft_reply


def _raw(mid: str) -> dict:
    return {
        "id": mid,
        "subject": "Invoice",
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": "Please pay."},
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": "c1",
    }


class _DraftSettings:
    mcp_sampling_timeout_seconds = 120.0


@pytest.mark.asyncio
async def test_draft_reply_sampling_success() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"mid","draft_reply":"Thanks.","subject":"RE: Invoice",'
        '"tone":"neutral","language":"en","confidence":0.9}'
    )
    sampling_result.model = "m1"

    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_raw("mid"))

    with patch("outlook_mcp.tools.email_drafter.get_settings", return_value=_DraftSettings()):
        with patch("outlook_mcp.tools.email_drafter.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_drafter.sampling_create_message",
                new_callable=AsyncMock,
                return_value=sampling_result,
            ):
                out = await draft_reply("mid", ctx)

    data = json.loads(out)
    assert data["sampling"] is True
    assert data["draft"]["draft_reply"] == "Thanks."
    assert data["draft"]["email_id"] == "mid"


@pytest.mark.asyncio
async def test_draft_reply_overwrites_wrong_email_id_in_response() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"wrong","draft_reply":"Hi","subject":"RE: X",'
        '"tone":"neutral","language":"en","confidence":0.5}'
    )
    sampling_result.model = "m1"

    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_raw("correct-id"))

    with patch("outlook_mcp.tools.email_drafter.get_settings", return_value=_DraftSettings()):
        with patch("outlook_mcp.tools.email_drafter.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_drafter.sampling_create_message",
                new_callable=AsyncMock,
                return_value=sampling_result,
            ):
                out = await draft_reply("correct-id", ctx)

    data = json.loads(out)
    assert data["draft"]["email_id"] == "correct-id"


@pytest.mark.asyncio
async def test_draft_reply_classification_context_truncated_and_wrapped() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"mid","draft_reply":"Ok","subject":"RE: Invoice",'
        '"tone":"neutral","language":"en","confidence":0.8}'
    )
    sampling_result.model = "m1"

    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_raw("mid"))
    long_ctx = "Z" * 5000

    captured: dict[str, str] = {}

    async def capture(_session: object, **kwargs: object) -> MagicMock:
        user_msg = kwargs["messages"][0]
        captured["user_text"] = user_msg.content.text
        return sampling_result

    with patch("outlook_mcp.tools.email_drafter.get_settings", return_value=_DraftSettings()):
        with patch("outlook_mcp.tools.email_drafter.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_drafter.sampling_create_message",
                new_callable=AsyncMock,
                side_effect=capture,
            ):
                await draft_reply("mid", ctx, classification_context=long_ctx)

    text = captured["user_text"]
    assert "BEGIN_UNTRUSTED_CLASSIFICATION_CONTEXT" in text
    ctx_block_start = text.index("BEGIN_UNTRUSTED_CLASSIFICATION_CONTEXT")
    ctx_block_end = text.index("---END_UNTRUSTED_CLASSIFICATION_CONTEXT---")
    ctx_block = text[ctx_block_start:ctx_block_end]
    assert ctx_block.count("Z") == 4000


@pytest.mark.asyncio
async def test_draft_reply_sampling_fallback() -> None:
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=_raw("mid"))

    with patch("outlook_mcp.tools.email_drafter.get_settings", return_value=_DraftSettings()):
        with patch("outlook_mcp.tools.email_drafter.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_drafter.sampling_create_message",
                new_callable=AsyncMock,
                side_effect=RuntimeError("sampling unavailable"),
            ):
                out = await draft_reply("mid", ctx)

    data = json.loads(out)
    assert data["sampling"] is False
    assert "email" in data
