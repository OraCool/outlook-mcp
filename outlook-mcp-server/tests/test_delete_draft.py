"""delete_draft: drafts only (GET isDraft first, DELETE only when true)."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import patch

import httpx
import pytest

from outlook_mcp import server
from outlook_mcp.auth.graph_client import GRAPH_BASE, GraphMailClient
from outlook_mcp.config import get_settings
from outlook_mcp.tools.email_writer import delete_draft

MSG_ID = "AAMkAGI2/draft+id=="  # contains characters that must be percent-encoded
ENC = "AAMkAGI2%2Fdraft%2Bid%3D%3D"


class _Enabled:
    enable_write_operations = True


class _Disabled:
    enable_write_operations = False


class FakeGraph:
    """Records requests; ``message`` is the GET body (None -> 404)."""

    def __init__(self, message: dict | None, delete_status: int = 204) -> None:
        self.message = message
        self.delete_status = delete_status
        self.calls: list[tuple[str, str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.raw_path.decode(), request.url.query.decode()))
        if request.method == "GET":
            if self.message is None:
                return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})
            return httpx.Response(200, json=self.message)
        return httpx.Response(self.delete_status)

    def client(self, mailbox: str | None = None) -> GraphMailClient:
        c = GraphMailClient("tok", mailbox=mailbox)
        transport = httpx.MockTransport(self.handler)
        c._client = lambda: httpx.AsyncClient(base_url=GRAPH_BASE, transport=transport)  # type: ignore[method-assign]
        return c


async def _run(fake: FakeGraph, mailbox: str | None = None, settings=_Enabled) -> dict:
    with (
        patch("outlook_mcp.tools.email_writer.get_settings", return_value=settings()),
        patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=fake.client(mailbox)),
    ):
        return json.loads(await delete_draft(ctx=None, message_id=MSG_ID))


@pytest.mark.asyncio
async def test_deletes_a_draft_get_then_delete() -> None:
    fake = FakeGraph({"id": MSG_ID, "isDraft": True})
    assert await _run(fake) == {"ok": True, "deleted": True}
    assert [c[0] for c in fake.calls] == ["GET", "DELETE"]
    assert fake.calls[0][1].startswith(f"/v1.0/me/messages/{ENC}")
    assert "select=id%2CisDraft" in fake.calls[0][2] or "select=id,isDraft" in fake.calls[0][2]
    assert fake.calls[1][1] == f"/v1.0/me/messages/{ENC}"


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [{"id": "m", "isDraft": False}, {"id": "m"}])
async def test_refuses_non_draft_without_delete(message: dict) -> None:
    fake = FakeGraph(message)
    assert await _run(fake) == {"ok": False, "error": "not_a_draft"}
    assert [c[0] for c in fake.calls] == ["GET"]


@pytest.mark.asyncio
async def test_not_found_on_get() -> None:
    fake = FakeGraph(None)
    assert await _run(fake) == {"ok": False, "error": "not_found"}
    assert [c[0] for c in fake.calls] == ["GET"]


@pytest.mark.asyncio
async def test_not_found_on_delete() -> None:
    fake = FakeGraph({"id": "m", "isDraft": True}, delete_status=404)
    assert await _run(fake) == {"ok": False, "error": "not_found"}


@pytest.mark.asyncio
async def test_other_http_error_reported() -> None:
    fake = FakeGraph({"id": "m", "isDraft": True}, delete_status=403)
    data = await _run(fake)
    assert data["error"] == "http_error" and data["status_code"] == 403


@pytest.mark.asyncio
async def test_write_disabled_makes_no_request() -> None:
    fake = FakeGraph({"id": "m", "isDraft": True})
    data = await _run(fake, settings=_Disabled)
    assert data["error"] == "write_disabled"
    assert "ENABLE_WRITE_OPERATIONS" in data["message"]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_application_mode_uses_users_path() -> None:
    fake = FakeGraph({"id": "m", "isDraft": True})
    assert (await _run(fake, mailbox="user@contoso.com"))["deleted"] is True
    assert all(c[1].startswith("/v1.0/users/user%40contoso.com/messages/") for c in fake.calls)


@pytest.mark.asyncio
async def test_logs_only_id_preview(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    await _run(FakeGraph({"id": "m", "isDraft": True}))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "delete_draft" in text
    assert MSG_ID not in text


def _names(monkeypatch, **env: str) -> set[str]:
    for key in ("MCP_ENABLED_TOOLS", "MCP_DISABLED_TOOLS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "false")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        return {t.name for t in asyncio.run(server.build_mcp().list_tools())}
    finally:
        get_settings.cache_clear()


def test_registered_by_default_and_via_allowlist(monkeypatch) -> None:
    assert "delete_draft" in _names(monkeypatch)
    names = _names(monkeypatch, MCP_ENABLED_TOOLS="delete_draft", ENABLE_WRITE_OPERATIONS="true")
    assert names == {"delete_draft"}


def test_unregistered_when_disabled(monkeypatch) -> None:
    assert "delete_draft" not in _names(monkeypatch, MCP_DISABLED_TOOLS="delete_draft")
    assert "delete_draft" not in _names(monkeypatch, MCP_ENABLED_TOOLS="list_inbox")


def test_enabling_without_writes_fails(monkeypatch) -> None:
    with pytest.raises(ValueError, match="ENABLE_WRITE_OPERATIONS"):
        _names(monkeypatch, MCP_ENABLED_TOOLS="delete_draft")
