"""get_email returns is_draft and Cc/Bcc recipients (full response level only)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from outlook_mcp.tools import email_reader

RAW = {
    "id": "m1",
    "subject": "Reminder",
    "isDraft": True,
    "toRecipients": [{"emailAddress": {"address": "office@example.com", "name": "Office"}}],
    "ccRecipients": [{"emailAddress": {"address": "cc@example.com", "name": None}}],
    "bccRecipients": [
        {"emailAddress": {"address": "a@example.org", "name": "A"}},
        {"emailAddress": {"address": "b@example.org", "name": "B"}},
    ],
}


async def _get(level: str) -> tuple[dict, AsyncMock]:
    client = AsyncMock()
    client.get_message = AsyncMock(return_value=RAW)
    settings = SimpleNamespace(pii_response_level=level, pii_redaction_strategy="pseudonymize", pii_entities="EMAIL_ADDRESS")
    with (
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=client),
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=settings),
    ):
        out = json.loads(await email_reader.get_email("m1", ctx=None))
    return out, client


@pytest.mark.asyncio
async def test_full_level_has_draft_flag_cc_and_bcc() -> None:
    out, client = await _get("full")
    select = client.get_message.call_args.kwargs["select"].split(",")
    assert {"ccRecipients", "bccRecipients", "isDraft"} <= set(select)
    assert out["is_draft"] is True
    assert out["cc_recipients"] == [{"address": "cc@example.com", "name": None}]
    assert [r["address"] for r in out["bcc_recipients"]] == ["a@example.org", "b@example.org"]


@pytest.mark.asyncio
async def test_minimal_level_keeps_only_draft_flag() -> None:
    out, _ = await _get("minimal")
    assert out["is_draft"] is True
    assert "cc_recipients" not in out
    assert "bcc_recipients" not in out


@pytest.mark.asyncio
async def test_missing_fields_are_empty() -> None:
    client = AsyncMock()
    client.get_message = AsyncMock(return_value={"id": "m2"})
    settings = SimpleNamespace(pii_response_level="full")
    with (
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=client),
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=settings),
    ):
        out = json.loads(await email_reader.get_email("m2", ctx=None))
    assert out["is_draft"] is None
    assert out["cc_recipients"] == [] and out["bcc_recipients"] == []
