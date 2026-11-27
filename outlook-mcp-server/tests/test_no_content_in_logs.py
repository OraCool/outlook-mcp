"""Mail content (subject, addresses, body, attachment and storage names) must not reach INFO+ logs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from outlook_mcp import server
from outlook_mcp.config import Settings, get_settings
from outlook_mcp.tools import email_reader, email_writer, mailbox_settings

PDF = (Path(__file__).parent / "fixtures" / "contract_sample.pdf").read_bytes()
MARKER = "ZZ_MARKER_9431"
ADDRESS = "zz@contoso.com"
CONTAINER = "https://contosostorage.blob.core.windows.net/attachments"
MSG = {
    "id": "msg-1",
    "subject": f"Invoice {MARKER}",
    "bodyPreview": f"{MARKER} preview",
    "body": {"contentType": "text", "content": f"Hello {MARKER} {ADDRESS}"},
    "from": {"emailAddress": {"name": MARKER, "address": ADDRESS}},
    "toRecipients": [{"emailAddress": {"name": MARKER, "address": ADDRESS}}],
    "receivedDateTime": "2026-11-01T10:00:00Z",
    "isRead": False,
}


class _S(Settings):
    enable_write_operations: bool = True
    graph_trust_request_headers: bool = False
    attachment_storage: str = "azure_blob"
    attachment_blob_container_url: str = CONTAINER
    attachment_allowed_prefixes: str = ""


def _client() -> AsyncMock:
    c = AsyncMock()
    c.get_message = AsyncMock(return_value={**MSG, "isDraft": True})
    c.list_inbox = AsyncMock(return_value={"value": [MSG]})
    c.resolve_mail_folder_id_by_display_name = AsyncMock(return_value="folder-1")
    c.search_messages = AsyncMock(return_value={"value": [MSG]})
    c.create_message_rule = AsyncMock(return_value={"id": "rule-1", "displayName": MARKER})
    c.update_message_rule = AsyncMock(return_value={"id": "rule-1", "displayName": MARKER})
    c.delete_message_rule = AsyncMock(return_value=None)
    c.create_master_category = AsyncMock(return_value={"id": "cat-1", "displayName": MARKER})
    c.delete_master_category = AsyncMock(return_value=None)
    c.create_mail_folder = AsyncMock(return_value={"id": "f-1", "displayName": MARKER})
    c.update_message = AsyncMock(return_value={"id": "m1"})
    c.delete_message = AsyncMock(return_value=None)
    c.move_message = AsyncMock(return_value={"id": "m2", "parentFolderId": "folder-1", "subject": MARKER})
    c.create_reply = AsyncMock(return_value={"id": "draft-1", "subject": f"RE: {MARKER}"})
    c.get_attachment = AsyncMock(
        return_value={
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "a1",
            "name": f"{MARKER}.pdf",
            "contentType": "application/pdf",
            "size": len(PDF),
        }
    )
    c.get_attachment_raw_bytes = AsyncMock(return_value=(PDF, "application/pdf"))
    return c


@pytest.mark.asyncio
async def test_no_content_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(201)))
    caplog.set_level(logging.DEBUG)
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=client),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=client),
        patch("outlook_mcp.tools.email_reader.get_managed_identity_token", return_value=("tok", 9)),
        patch("outlook_mcp.tools.email_reader._storage_http_client", return_value=http),
    ):
        outs = [
            await email_reader.list_inbox(ctx=None, folder_name=f"{MARKER} folder"),
            await email_reader.get_email(f"{MARKER}-{ADDRESS}", ctx=None),
            await email_reader.get_attachment_text(f"{MARKER}-id", "a1", ctx=None),
            await email_reader.save_attachment_to_storage(f"{MARKER}-id", "a1", f"Docs/{MARKER}/x.pdf", ctx=None),
            await email_writer.create_reply_draft(ctx=None, message_id=f"{MARKER}-id", comment=f"{MARKER} {ADDRESS}"),
        ]
    # The tools really ran (not an early error), so the absence of the marker in logs means something.
    assert json.loads(outs[0])["count"] == 1
    assert MARKER in outs[1]
    assert json.loads(outs[2])["ok"] is True
    assert json.loads(outs[3])["ok"] is True
    assert json.loads(outs[4])["ok"] is True

    leaked = _leaked(caplog)
    assert leaked == []


def _leaked(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.INFO and (MARKER in r.getMessage() or ADDRESS in r.getMessage())
    ]


@pytest.mark.asyncio
async def test_no_names_or_queries_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Tools that take user/mail content as arguments (search query, rule/category/folder names, ids)."""
    client = _client()
    caplog.set_level(logging.DEBUG)
    ident = f"{MARKER}-{ADDRESS}"
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.mailbox_settings.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=client),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=client),
        patch("outlook_mcp.tools.mailbox_settings.make_graph_client", return_value=client),
    ):
        outs = [
            await email_reader.search_emails(f"from:{ADDRESS} {MARKER}", ctx=None),
            await email_reader.get_attachment_content(ident, ident, ctx=None),
            await mailbox_settings.create_message_rule(
                ctx=None,
                display_name=f"{MARKER} rule",
                sequence=1,
                conditions={"subjectContains": [MARKER]},
                actions={"markAsRead": True},
            ),
            await mailbox_settings.update_message_rule(ctx=None, rule_id=ident, display_name=f"{MARKER} rule"),
            await mailbox_settings.delete_message_rule(ctx=None, rule_id=ident),
            await mailbox_settings.create_master_category(ctx=None, display_name=f"{MARKER} cat"),
            await mailbox_settings.delete_master_category(ctx=None, category_id=ident),
            await email_writer.create_mail_folder(ctx=None, display_name=f"{MARKER} folder"),
            await email_writer.mark_as_read(ctx=None, message_id=ident),
            await email_writer.set_message_categories(ctx=None, message_id=ident, categories=[MARKER]),
            await email_writer.move_email(ctx=None, message_id=ident, destination_folder_id=ident),
            await email_writer.delete_draft(ctx=None, message_id=ident),
        ]
    # Each tool ran past argument validation (otherwise the empty-log assertion proves nothing).
    for out in outs:
        assert "validation_error" not in out and "write_disabled" not in out, out
    assert _leaked(caplog) == []


def test_log_level_default_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    root, pkg = logging.getLogger(), logging.getLogger("outlook_mcp")
    before = (root.level, pkg.level)
    get_settings.cache_clear()
    try:
        server.build_mcp()
        assert (root.level, pkg.level) == before
    finally:
        get_settings.cache_clear()


def test_log_level_setting_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    root, pkg = logging.getLogger(), logging.getLogger("outlook_mcp")
    before = (root.level, pkg.level)
    monkeypatch.setenv("LOG_LEVEL", "warning")
    get_settings.cache_clear()
    try:
        server.build_mcp()
        assert root.level == logging.WARNING
        assert pkg.level == logging.WARNING
    finally:
        root.setLevel(before[0])
        pkg.setLevel(before[1])
        get_settings.cache_clear()


def test_log_level_invalid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings()
