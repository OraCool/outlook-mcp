"""Classification prompt content."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.models.email import DEFAULT_CLASSIFICATION_CATEGORIES
from outlook_mcp.tools._email_prompt import BEGIN_UNTRUSTED_EMAIL_JSON
from outlook_mcp.tools.email_classifier import (
    CLASSIFICATION_SYSTEM,
    apply_llm_category_to_email,
    build_classification_system_prompt,
    categorize_email,
)


def test_classification_prompt_lists_categories() -> None:
    assert "INVOICE_DISPUTE" in CLASSIFICATION_SYSTEM
    assert "PAYMENT_PROMISE" in CLASSIFICATION_SYSTEM
    assert "UNCLASSIFIED" in CLASSIFICATION_SYSTEM
    assert "confidence" in CLASSIFICATION_SYSTEM
    assert "untrusted" in CLASSIFICATION_SYSTEM.lower()
    assert CLASSIFICATION_SYSTEM == build_classification_system_prompt(DEFAULT_CLASSIFICATION_CATEGORIES)


def test_build_classification_system_prompt_sorted_category_line() -> None:
    prompt = build_classification_system_prompt(frozenset({"ZZZ", "AAA", "UNCLASSIFIED"}))
    assert "Allowed categories (use the exact string):" in prompt
    assert "AAA, UNCLASSIFIED, ZZZ" in prompt


@pytest.mark.asyncio
async def test_categorize_email_sampling_uses_system_prompt_and_delimiters() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"mid","category":"UNCLASSIFIED","confidence":0.5,'
        '"intent":{"customer_statement":"","required_action":"","urgency":"LOW"},'
        '"reasoning":"","extracted_data":{"invoice_numbers":[]},"escalation":{}}'
    )
    sampling_result.model = "m"

    session = MagicMock()
    session.create_message = AsyncMock(return_value=sampling_result)

    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw_msg = {
        "id": "mid",
        "subject": "s",
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": "c"},
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": "c1",
        "categories": [],
    }
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw_msg)

    class _SamplingSettings:
        mcp_sampling_timeout_seconds = 120.0

        def classification_category_set(self) -> frozenset[str]:
            return DEFAULT_CLASSIFICATION_CATEGORIES

    with patch("outlook_mcp.tools.email_classifier.get_settings", return_value=_SamplingSettings()):
        with patch("outlook_mcp.tools.email_classifier.make_graph_client", return_value=mock_client):
            await categorize_email("mid", ctx)

    kwargs = session.create_message.await_args.kwargs
    assert kwargs.get("system_prompt") == CLASSIFICATION_SYSTEM
    user_msg = kwargs["messages"][0]
    assert BEGIN_UNTRUSTED_EMAIL_JSON in user_msg.content.text
    assert "authoritative_message_id: mid" in user_msg.content.text


@pytest.mark.asyncio
async def test_categorize_email_sampling_uses_configured_taxonomy_in_prompt() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"mid","category":"UNCLASSIFIED","confidence":0.5,'
        '"intent":{"customer_statement":"","required_action":"","urgency":"LOW"},'
        '"reasoning":"","extracted_data":{"invoice_numbers":[]},"escalation":{}}'
    )
    sampling_result.model = "m"

    session = MagicMock()
    session.create_message = AsyncMock(return_value=sampling_result)

    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw_msg = {
        "id": "mid",
        "subject": "s",
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": "c"},
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": "c1",
        "categories": [],
    }
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw_msg)

    class _CustomTaxonomy:
        mcp_sampling_timeout_seconds = 120.0

        def classification_category_set(self) -> frozenset[str]:
            return frozenset({"MY_CAT_A", "MY_CAT_B", "UNCLASSIFIED"})

    with patch("outlook_mcp.tools.email_classifier.get_settings", return_value=_CustomTaxonomy()):
        with patch("outlook_mcp.tools.email_classifier.make_graph_client", return_value=mock_client):
            await categorize_email("mid", ctx)

    sp = session.create_message.await_args.kwargs.get("system_prompt", "")
    assert "MY_CAT_A" in sp
    assert "MY_CAT_B" in sp
    assert "INVOICE_DISPUTE" not in sp


@pytest.mark.asyncio
async def test_apply_llm_category_to_email_patches_graph() -> None:
    sampling_result = MagicMock()
    sampling_result.content = MagicMock()
    sampling_result.content.text = (
        '{"email_id":"mid","category":"UNCLASSIFIED","confidence":0.5,'
        '"intent":{"customer_statement":"","required_action":"","urgency":"LOW"},'
        '"reasoning":"","extracted_data":{"invoice_numbers":[]},"escalation":{}}'
    )
    sampling_result.model = "m"

    session = MagicMock()
    session.create_message = AsyncMock(return_value=sampling_result)

    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw_msg = {
        "id": "mid",
        "subject": "s",
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": "c"},
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": "c1",
        "categories": [],
    }
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw_msg)
    mock_client.update_message = AsyncMock(return_value={})

    class _WritesOn:
        enable_write_operations = True

    with patch("outlook_mcp.tools.email_classifier.make_graph_client", return_value=mock_client):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=mock_client):
            with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_WritesOn()):
                out = await apply_llm_category_to_email("mid", ctx)

    data = json.loads(out)
    assert data["ok"] is True
    assert data["categories"] == ["UNCLASSIFIED"]
    assert data["classification"]["category"] == "UNCLASSIFIED"
    mock_client.update_message.assert_awaited_once_with(
        "mid",
        {"categories": ["UNCLASSIFIED"]},
    )


@pytest.mark.asyncio
async def test_apply_llm_category_to_email_skips_patch_when_sampling_fails() -> None:
    session = MagicMock()
    session.create_message = AsyncMock(side_effect=RuntimeError("no sampling"))

    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw_msg = {
        "id": "mid",
        "subject": "s",
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": "c"},
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": "c1",
        "categories": [],
    }
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw_msg)

    class _WritesOn:
        enable_write_operations = True

    with patch("outlook_mcp.tools.email_classifier.make_graph_client", return_value=mock_client):
        with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_WritesOn()):
            out = await apply_llm_category_to_email("mid", ctx)

    data = json.loads(out)
    assert data["error"] == "classification_failed"
    mock_client.update_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_categorize_email_sampling_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_create_message(*_a: object, **_kw: object) -> None:
        await asyncio.sleep(30.0)

    session = MagicMock()
    session.create_message = AsyncMock(side_effect=slow_create_message)

    ctx = MagicMock()
    ctx.session = session
    ctx.log = AsyncMock()
    ctx.report_progress = AsyncMock()

    raw_msg = {
        "id": "mid",
        "subject": "s",
        "bodyPreview": "p",
        "body": {"contentType": "text", "content": "c"},
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "from": {"emailAddress": {"address": "a@b.c"}},
        "sender": None,
        "toRecipients": [],
        "conversationId": "c1",
        "categories": [],
    }
    mock_client = AsyncMock()
    mock_client.get_message = AsyncMock(return_value=raw_msg)

    class _FastTimeout:
        mcp_sampling_timeout_seconds = 0.15

        def classification_category_set(self) -> frozenset[str]:
            return DEFAULT_CLASSIFICATION_CATEGORIES

    monkeypatch.setattr(
        "outlook_mcp.tools.email_classifier.get_settings",
        lambda: _FastTimeout(),
    )

    with patch("outlook_mcp.tools.email_classifier.make_graph_client", return_value=mock_client):
        out = await categorize_email("mid", ctx)

    data = json.loads(out)
    assert data["sampling"] is False
    assert "timed out" in data["sampling_error"].lower()
