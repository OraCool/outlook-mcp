"""Tool-aware server instructions and MCP_INSTRUCTIONS_APPEND."""

from __future__ import annotations

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from outlook_mcp import server
from outlook_mcp.config import get_settings
from outlook_mcp.instructions import APPEND_MAX_CHARS

CLOUD = (
    "list_inbox,get_email,search_emails,get_thread,list_folders,create_mail_folder,get_attachments,"
    "get_attachment_content,get_attachment_text,save_attachment_to_storage,create_draft,create_reply_draft,"
    "move_email,move_emails,mark_as_read,set_message_categories,set_messages_categories,list_message_rules,"
    "delete_draft"
)


def _build(monkeypatch, **env: str):
    for key in ("MCP_ENABLED_TOOLS", "MCP_DISABLED_TOOLS", "MCP_INSTRUCTIONS_APPEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "false")
    monkeypatch.setenv("ATTACHMENT_STORAGE", "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        return server.build_mcp()
    finally:
        get_settings.cache_clear()


def test_only_registered_tools_are_mentioned(monkeypatch):
    text = _build(monkeypatch, MCP_ENABLED_TOOLS="list_inbox,get_email").instructions
    assert "list_inbox" in text
    assert "delete_draft" not in text
    assert "create_draft" not in text
    assert "search_emails" not in text
    assert "KQL" not in text
    assert "AR Email Management" not in text


def test_no_sending_line_when_send_tools_absent(monkeypatch):
    text = _build(
        monkeypatch, MCP_DISABLED_TOOLS="send_email,send_draft_email"
    ).instructions
    assert "does not allow sending" in text
    default = _build(monkeypatch).instructions
    assert "does not allow sending" not in default


def test_cloud_tool_set(monkeypatch):
    text = _build(
        monkeypatch,
        ENABLE_WRITE_OPERATIONS="true",
        MCP_ENABLED_TOOLS=CLOUD,
        ATTACHMENT_STORAGE="azure_blob",
        ATTACHMENT_BLOB_CONTAINER_URL="https://contosostorage.blob.core.windows.net/attachments",
    ).instructions
    for needle in (
        "search_emails",
        "get_thread",
        "create_draft",
        "bcc_addresses",
        "create_reply_draft",
        "not_a_draft",
        "get_attachment_text",
        "save_attachment_to_storage",
        "queued",
        "does not allow sending",
    ):
        assert needle in text
    assert "save_attachment_to_path" not in text
    assert len(text.splitlines()) <= 25


def test_append_is_added_and_capped(monkeypatch):
    base = _build(monkeypatch).instructions
    text = _build(
        monkeypatch, MCP_INSTRUCTIONS_APPEND="Team hint: use folder Invoices."
    ).instructions
    assert text.startswith(base)
    assert text.endswith("Team hint: use folder Invoices.")
    long = _build(
        monkeypatch, MCP_INSTRUCTIONS_APPEND="Z" * (APPEND_MAX_CHARS + 500)
    ).instructions
    assert long.count("Z") == APPEND_MAX_CHARS


def test_append_not_logged(monkeypatch, caplog):
    caplog.set_level("DEBUG")
    _build(monkeypatch, MCP_INSTRUCTIONS_APPEND="secret-hint-123")
    assert "secret-hint-123" not in caplog.text


@pytest.mark.anyio
async def test_initialize_result_carries_instructions(monkeypatch):
    app = _build(monkeypatch, MCP_INSTRUCTIONS_APPEND="deployment hint")
    low = app._lowlevel_server
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(
                    server_streams[0],
                    server_streams[1],
                    low.create_initialization_options(),
                    raise_exceptions=True,
                )
            )
            async with ClientSession(*client_streams) as session:
                result = await session.initialize()
            tg.cancel_scope.cancel()
    assert result.instructions == app.instructions
    assert "deployment hint" in result.instructions


def test_date_example_uses_range_syntax(monkeypatch):
    text = _build(monkeypatch).instructions
    assert "received:2026-01-01..2026-01-31" in text
    assert "received>=" not in text


def test_folder_line_gating(monkeypatch):
    only_cat = _build(monkeypatch, MCP_ENABLED_TOOLS="set_message_categories", ENABLE_WRITE_OPERATIONS="true").instructions
    assert "case-insensitively" not in only_cat
    assert "Prefer" not in only_cat
    inbox = _build(monkeypatch, MCP_ENABLED_TOOLS="list_inbox").instructions
    assert "case-insensitively" in inbox
    assert "Prefer" not in inbox
    batch = _build(monkeypatch, MCP_ENABLED_TOOLS="move_emails,set_messages_categories", ENABLE_WRITE_OPERATIONS="true").instructions
    assert "Prefer move_emails / set_messages_categories" in batch
