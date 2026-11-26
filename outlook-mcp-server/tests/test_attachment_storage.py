"""save_attachment_to_storage: key validation, blob PUT, tool wiring."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from outlook_mcp import server
from outlook_mcp.config import Settings, get_settings
from outlook_mcp.storage.azure_blob import (
    StorageConfigError,
    normalize_container_url,
    put_blob,
    validate_storage_key,
)

CONTAINER = "https://contosostorage.blob.core.windows.net/attachments"
SAMPLE_KEY = "Документы/2026/Группа-А/1.1/Архив/20260101-01 Иванова — квитанция 0000-0000.pdf"


@pytest.mark.parametrize("key", [SAMPLE_KEY, "a/«Имя» (2).pdf"])
def test_key_accepts_cyrillic_names(key: str) -> None:
    assert validate_storage_key(key, []) == key


def test_key_is_nfc_normalized() -> None:
    decomposed = "Й/a.pdf".replace("Й", "Й")
    assert validate_storage_key(decomposed, []) == "Й/a.pdf"


@pytest.mark.parametrize(
    ("key", "code"),
    [
        ("", "empty"),
        ("/a.pdf", "absolute"),
        ("a/../b.pdf", "dotdot"),
        ("a\\b.pdf", "backslash"),
        ("a//b.pdf", "empty_segment"),
        ("a/\x07b.pdf", "control_char"),
        ("x" * 1025, "too_long"),
        ("a/\uff0e\uff0e/b.pdf", "dotdot"),
        ("a/\u2025/b.pdf", "dotdot"),
        ("a\uff0fb.pdf", "confusable"),
        ("a/\u202eb.pdf", "control_char"),
        ("a/\u200bb.pdf", "control_char"),
        ("a/\ufeffb.pdf", "control_char"),
        ("a/\u2028b.pdf", "control_char"),
        ("a/\u2029b.pdf", "control_char"),
        ("a/\ud800b.pdf", "control_char"),
        (" a.pdf", "bad_segment_edge"),
        ("a /b.pdf", "bad_segment_edge"),
        ("a/b.", "bad_segment_edge"),
    ],
)
def test_key_rejects(key: str, code: str) -> None:
    with pytest.raises(ValueError) as ei:
        validate_storage_key(key, [])
    assert str(ei.value) == code


def test_prefix_enforced() -> None:
    assert validate_storage_key("Документы/x.pdf", ["Документы/"]) == "Документы/x.pdf"
    with pytest.raises(ValueError) as ei:
        validate_storage_key("Other/x.pdf", ["Документы/"])
    assert str(ei.value) == "prefix_not_allowed"


def test_prefix_not_bypassed_by_dotdot() -> None:
    with pytest.raises(ValueError) as ei:
        validate_storage_key("Документы/../Other/x.pdf", ["Документы/"])
    assert str(ei.value) == "dotdot"


def test_prefix_setting_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTACHMENT_ALLOWED_PREFIXES", "Документы/")
    get_settings.cache_clear()
    try:
        assert get_settings().attachment_allowed_prefixes == "Документы/"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://contosostorage.blob.core.windows.net/attachments",
        "https://example.com/attachments",
        "https://contosostorage.blob.core.windows.net",
        "https://contosostorage.blob.core.windows.net/a/b",
        "https://contosostorage.blob.core.windows.net/attachments?sv=x",
        "https://evil.com/x@contosostorage.blob.core.windows.net/attachments",
    ],
)
def test_container_url_rejected(url: str) -> None:
    with pytest.raises(StorageConfigError):
        normalize_container_url(url)


def test_container_url_accepts_trailing_slash() -> None:
    assert normalize_container_url(CONTAINER + "/") == CONTAINER


def test_put_blob_encodes_segments() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    put_blob(CONTAINER, "Документы/a b.pdf", b"data", "application/pdf", "tok", http)
    req = seen[0]
    assert req.method == "PUT"
    assert req.url.raw_path.decode() == "/attachments/%D0%94%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD%D1%82%D1%8B/a%20b.pdf"
    assert req.headers["x-ms-blob-type"] == "BlockBlob"
    assert req.headers["x-ms-version"] == "2023-11-03"
    assert req.headers["authorization"] == "Bearer tok"
    assert req.content == b"data"


def test_put_blob_error_status_raises() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(httpx.HTTPStatusError):
        put_blob(CONTAINER, "a.pdf", b"x", "application/pdf", "tok", http)


# --- tool wiring -----------------------------------------------------------------------------


def _names(monkeypatch: pytest.MonkeyPatch, **env: str) -> set[str]:
    for key in ("MCP_ENABLED_TOOLS", "MCP_DISABLED_TOOLS", "ATTACHMENT_STORAGE", "ATTACHMENT_BLOB_CONTAINER_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "false")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        return {t.name for t in asyncio.run(server.build_mcp().list_tools())}
    finally:
        get_settings.cache_clear()


def test_tool_not_registered_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "save_attachment_to_storage" not in _names(monkeypatch)
    assert "save_attachment_to_storage" not in _names(monkeypatch, ATTACHMENT_STORAGE="azure_blob")


def test_tool_registered_with_config(monkeypatch: pytest.MonkeyPatch) -> None:
    names = _names(monkeypatch, ATTACHMENT_STORAGE="azure_blob", ATTACHMENT_BLOB_CONTAINER_URL=CONTAINER)
    assert "save_attachment_to_storage" in names


def test_tool_enabled_without_config_names_missing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="ATTACHMENT_BLOB_CONTAINER_URL"):
        _names(monkeypatch, MCP_ENABLED_TOOLS="save_attachment_to_storage")


class _S(Settings):
    enable_write_operations: bool = True
    graph_trust_request_headers: bool = False
    attachment_storage: str = "azure_blob"
    attachment_blob_container_url: str = CONTAINER
    attachment_allowed_prefixes: str = "Документы/"
    azure_client_id: str = "mi-client"


def _graph_client(data: bytes = b"%PDF-1") -> AsyncMock:
    c = AsyncMock()
    c.get_attachment = AsyncMock(
        return_value={
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "k.pdf",
            "contentType": "application/pdf",
        }
    )
    c.get_attachment_raw_bytes = AsyncMock(return_value=(data, "application/pdf"))
    return c


async def _call(key: str, settings: Settings, handler, client=None) -> str:
    from outlook_mcp.tools import email_reader

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=settings),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=client or _graph_client()),
        patch("outlook_mcp.tools.email_reader.get_managed_identity_token", return_value=("secret-token", 9)) as tok,
        patch("outlook_mcp.tools.email_reader._storage_http_client", return_value=http),
    ):
        out = await email_reader.save_attachment_to_storage("m1", "a1", key, ctx=None)
    tok.assert_called_once()
    assert tok.call_args.args == ("https://storage.azure.com/",)
    assert tok.call_args.kwargs["client_id"] == "mi-client"
    return out


@pytest.mark.asyncio
async def test_tool_result_shape() -> None:
    puts: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        puts.append(r)
        return httpx.Response(201)

    out = json.loads(await _call("Документы/x.pdf", _S(), handler))
    assert out == {"ok": True, "queued": True, "key": "Документы/x.pdf", "bytes": 6}
    assert puts[0].content == b"%PDF-1"


@pytest.mark.asyncio
async def test_tool_refuses_without_writes() -> None:
    s = _S(enable_write_operations=False)
    out = json.loads(await _call_no_token("Документы/x.pdf", s))
    assert out["error"] == "write_disabled"


@pytest.mark.asyncio
async def test_tool_refuses_when_request_headers_are_trusted() -> None:
    # Graph identity could be the caller's (header token) while storage uses the server's identity.
    from outlook_mcp.tools import email_reader

    graph = MagicMock(side_effect=AssertionError("must not reach Graph"))
    mi = MagicMock(side_effect=AssertionError("must not request a storage token"))
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S(graph_trust_request_headers=True)),
        patch("outlook_mcp.tools.email_reader.make_graph_client", graph),
        patch("outlook_mcp.tools.email_reader.get_managed_identity_token", mi),
    ):
        out = json.loads(await email_reader.save_attachment_to_storage("m1", "a1", "Документы/x.pdf", ctx=None))
    assert out["error"] == "configuration_error"
    assert "GRAPH_TRUST_REQUEST_HEADERS=false" in out["message"]
    graph.assert_not_called()
    mi.assert_not_called()


@pytest.mark.asyncio
async def test_tool_allowed_when_request_headers_not_trusted() -> None:
    out = json.loads(await _call("Документы/x.pdf", _S(graph_trust_request_headers=False), lambda r: httpx.Response(201)))
    assert out["ok"] is True


async def _call_no_token(key: str, settings: Settings) -> str:
    from outlook_mcp.tools import email_reader

    with patch("outlook_mcp.tools.email_reader.get_settings", return_value=settings):
        return await email_reader.save_attachment_to_storage("m1", "a1", key, ctx=None)


@pytest.mark.asyncio
async def test_tool_invalid_key_and_prefix() -> None:
    from outlook_mcp.tools import email_reader

    with patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()):
        out = json.loads(await email_reader.save_attachment_to_storage("m1", "a1", "Other/x.pdf", ctx=None))
    assert out == {"error": "invalid_key", "reason": "prefix_not_allowed"}


@pytest.mark.asyncio
async def test_tool_bad_container_url_is_configuration_error() -> None:
    from outlook_mcp.tools import email_reader

    s = _S(attachment_blob_container_url="https://example.com/x")
    with patch("outlook_mcp.tools.email_reader.get_settings", return_value=s):
        out = json.loads(await email_reader.save_attachment_to_storage("m1", "a1", "Документы/x.pdf", ctx=None))
    assert out["error"] == "configuration_error"


@pytest.mark.asyncio
async def test_tool_storage_error_has_no_token_or_key() -> None:
    out = await _call("Документы/x.pdf", _S(), lambda r: httpx.Response(403, headers={"x-ms-error-code": "AuthorizationFailure"}))
    data = json.loads(out)
    assert data["error"] == "storage_error"
    assert data["status_code"] == 403
    assert "secret-token" not in out
    assert "x.pdf" not in out


@pytest.mark.asyncio
async def test_tool_nothing_logged() -> None:
    from outlook_mcp.tools import email_reader

    logged: list[str] = []

    async def capture(ctx, message, **kw):
        logged.append(message)

    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(201)))
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=_graph_client()),
        patch("outlook_mcp.tools.email_reader.get_managed_identity_token", return_value=("secret-token", 9)),
        patch("outlook_mcp.tools.email_reader._storage_http_client", return_value=http),
        patch("outlook_mcp.tools.email_reader.tool_log_info", capture),
        patch("outlook_mcp.tools.email_reader.tool_log_warning", capture),
    ):
        await email_reader.save_attachment_to_storage("m1", "a1", "Документы/конфиденциально.pdf", ctx=None)
    joined = " ".join(logged)
    assert "конфиденциально" not in joined and "k.pdf" not in joined and "secret-token" not in joined


def test_prefix_is_segment_bounded() -> None:
    with pytest.raises(ValueError) as ei:
        validate_storage_key("Документы-evil/x.pdf", ["Документы"])
    assert str(ei.value) == "prefix_not_allowed"
    assert validate_storage_key("Документы/x.pdf", ["Документы"]) == "Документы/x.pdf"
    assert validate_storage_key("Документы/x.pdf", ["Документы/"]) == "Документы/x.pdf"


def test_configured_prefixes_are_validated() -> None:
    from outlook_mcp.storage.azure_blob import parse_allowed_prefixes

    assert parse_allowed_prefixes("Документы/, A/b") == ["Документы", "A/b"]
    for bad in ("../x", "a\\b", "a/\u202e"):
        with pytest.raises(StorageConfigError):
            parse_allowed_prefixes(bad)


@pytest.mark.parametrize(
    "url",
    [
        "https://contosostorage.blob.core.windows.net:abc/attachments",
        "https://contosostorage.blob.core.windows.net/A",
        "https://contosostorage.blob.core.windows.net/a--b",
        "https://contosostorage.blob.core.windows.net/-ab",
    ],
)
def test_container_url_more_rejections(url: str) -> None:
    with pytest.raises(StorageConfigError):
        normalize_container_url(url)


def test_container_root_allowed() -> None:
    assert normalize_container_url("https://contosostorage.blob.core.windows.net/$root").endswith("/$root")


def test_httpx_loggers_quiet_after_build(monkeypatch: pytest.MonkeyPatch) -> None:
    import logging

    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    _names(monkeypatch)
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


@pytest.mark.asyncio
async def test_tool_unexpected_exception_does_not_escape() -> None:
    from outlook_mcp.tools import email_reader

    class Boom:
        def __enter__(self):
            raise UnicodeEncodeError("utf-8", "x", 0, 1, "boom")

        def __exit__(self, *a):
            return False

    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=_graph_client()),
        patch("outlook_mcp.tools.email_reader.get_managed_identity_token", return_value=("secret-token", 9)),
        patch("outlook_mcp.tools.email_reader._storage_http_client", return_value=Boom()),
    ):
        out = json.loads(await email_reader.save_attachment_to_storage("m1", "a1", "Документы/x.pdf", ctx=None))
    assert out["error"] == "storage_error"
