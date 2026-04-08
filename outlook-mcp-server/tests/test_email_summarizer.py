"""Tests for email_summarizer MCP tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.tools import email_summarizer
from outlook_mcp.tools.email_summarizer import summarize_email, summarize_thread


def _msg(mid: str, subject: str, dt: str, conv: str = "conv-xyz") -> dict:
    return {
        "id": mid,
        "subject": subject,
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": f"content-{subject}-x" * 40},
        "receivedDateTime": dt,
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": conv,
    }


class _SummarizeSettings:
    mcp_sampling_timeout_seconds = 120.0


@pytest.mark.asyncio
async def test_summarize_email_sampling_success() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"mid","summary":"S","key_entities":'
        '{"invoice_numbers":[],"amounts":[],"dates":[],"company_name":null},"language":"en"}'
    )
    sampling_result.model = "m1"

    session = MagicMock()
    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw = _msg("mid", "Subj", "2024-01-01T00:00:00Z")
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw)

    with patch("outlook_mcp.tools.email_summarizer.get_settings", return_value=_SummarizeSettings()):
        with patch("outlook_mcp.tools.email_summarizer.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_summarizer.sampling_create_message",
                new_callable=AsyncMock,
                return_value=sampling_result,
            ):
                out = await summarize_email("mid", ctx)

    data = json.loads(out)
    assert data["sampling"] is True
    assert data["summarization"]["email_id"] == "mid"
    assert data["summarization"]["summary"] == "S"


@pytest.mark.asyncio
async def test_summarize_email_sampling_fallback() -> None:
    session = MagicMock()
    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw = _msg("mid", "Subj", "2024-01-01T00:00:00Z")
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw)

    with patch("outlook_mcp.tools.email_summarizer.get_settings", return_value=_SummarizeSettings()):
        with patch("outlook_mcp.tools.email_summarizer.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_summarizer.sampling_create_message",
                new_callable=AsyncMock,
                side_effect=RuntimeError("no sampling"),
            ):
                out = await summarize_email("mid", ctx)

    data = json.loads(out)
    assert data["sampling"] is False
    assert "sampling_error" in data
    assert "email" in data


@pytest.mark.asyncio
async def test_summarize_thread_prompt_lists_newest_message_first() -> None:
    """list_messages_by_conversation is oldest-first; prompt should lead with the latest message."""
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"conversation_id":"c","summary":"S","key_facts":'
        '{"invoice_numbers":[],"amounts":[],"commitments":[],"open_issues":[],"timeline":[]},'
        '"thread_state":"pending_action"}'
    )
    sampling_result.model = "m1"

    session = MagicMock()
    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    thread_value = [
        _msg("old", "OLD", "2024-01-01T00:00:00Z"),
        _msg("mid", "MID", "2024-01-02T00:00:00Z"),
        _msg("new", "NEW", "2024-01-03T00:00:00Z"),
    ]
    mock_client = AsyncMock()
    mock_client.list_messages_by_conversation = AsyncMock(
        return_value={"value": thread_value},
    )

    captured: dict[str, str] = {}

    async def capture_sampling(_session: object, **kwargs: object) -> MagicMock:
        user_msg = kwargs["messages"][0]
        captured["user_text"] = user_msg.content.text
        return sampling_result

    with patch("outlook_mcp.tools.email_summarizer.get_settings", return_value=_SummarizeSettings()):
        with patch("outlook_mcp.tools.email_summarizer.make_graph_client", return_value=mock_client):
            with patch(
                "outlook_mcp.tools.email_summarizer.sampling_create_message",
                new_callable=AsyncMock,
                side_effect=capture_sampling,
            ):
                await summarize_thread("conv-xyz", ctx)

    text = captured["user_text"]
    pos_new = text.find('"NEW"')
    pos_old = text.find('"OLD"')
    assert pos_new != -1 and pos_old != -1
    assert pos_new < pos_old


@pytest.mark.asyncio
async def test_summarize_thread_truncation_omits_oldest_messages() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"conversation_id":"c","summary":"S","key_facts":'
        '{"invoice_numbers":[],"amounts":[],"commitments":[],"open_issues":[],"timeline":[]},'
        '"thread_state":"pending_action"}'
    )
    sampling_result.model = "m1"

    session = MagicMock()
    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    thread_value = [
        _msg("old", "OLD", "2024-01-01T00:00:00Z"),
        _msg("mid", "MID", "2024-01-02T00:00:00Z"),
        _msg("new", "NEW", "2024-01-03T00:00:00Z"),
    ]
    mock_client = AsyncMock()
    mock_client.list_messages_by_conversation = AsyncMock(
        return_value={"value": thread_value},
    )

    captured: dict[str, str] = {}

    async def capture_sampling(_session: object, **kwargs: object) -> MagicMock:
        user_msg = kwargs["messages"][0]
        captured["user_text"] = user_msg.content.text
        return sampling_result

    with patch.object(email_summarizer, "_MAX_THREAD_PROMPT_CHARS", 2800):
        with patch("outlook_mcp.tools.email_summarizer.get_settings", return_value=_SummarizeSettings()):
            with patch("outlook_mcp.tools.email_summarizer.make_graph_client", return_value=mock_client):
                with patch(
                    "outlook_mcp.tools.email_summarizer.sampling_create_message",
                    new_callable=AsyncMock,
                    side_effect=capture_sampling,
                ):
                    await summarize_thread("conv-xyz", ctx)

    text = captured["user_text"]
    assert "older message(s) were omitted" in text
    assert '"NEW"' in text
    assert '"MID"' in text
    assert '"OLD"' not in text
