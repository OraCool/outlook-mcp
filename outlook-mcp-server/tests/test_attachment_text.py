"""get_attachment_text: PDF text extraction from a Graph attachment."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from outlook_mcp.tools import email_reader

FIX = Path(__file__).parent / "fixtures"


class _S:
    attachment_text_max_bytes = 15_000_000
    attachment_text_max_pages = 200
    attachment_text_timeout_seconds = 30.0


class _Tiny(_S):
    attachment_text_max_bytes = 10


def _client(raw: bytes, size: int | None = None) -> AsyncMock:
    c = AsyncMock()
    c.get_attachment = AsyncMock(
        return_value={
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "a1",
            "name": "x.bin",
            "contentType": "application/octet-stream",
            "size": len(raw) if size is None else size,
        }
    )
    c.get_attachment_raw_bytes = AsyncMock(return_value=(raw, "application/octet-stream"))
    return c


async def _call(raw: bytes, settings=_S, size: int | None = None, **kw) -> dict:
    c = _client(raw, size)
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=settings()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=c),
    ):
        out = json.loads(await email_reader.get_attachment_text("m1", "a1", ctx=None, **kw))
    out["_client"] = c
    return out


@pytest.mark.asyncio
async def test_pdf_text_extracted() -> None:
    out = await _call((FIX / "contract_sample.pdf").read_bytes())
    assert out["ok"] is True
    assert out["pages"] >= 1
    assert out["truncated"] is False
    for marker in ("Section I", "Signature", "Error! Reference source not found."):
        assert marker in out["text"]


@pytest.mark.asyncio
async def test_not_pdf() -> None:
    out = await _call((FIX / "not_a_pdf.bin").read_bytes())
    assert out == {"ok": False, "error": "not_pdf", "_client": out["_client"]}


@pytest.mark.asyncio
async def test_too_large_by_metadata_skips_download() -> None:
    out = await _call((FIX / "contract_sample.pdf").read_bytes(), settings=_Tiny)
    assert out["error"] == "too_large"
    out["_client"].get_attachment_raw_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_too_large_by_actual_length() -> None:
    raw = (FIX / "contract_sample.pdf").read_bytes()
    out = await _call(raw, settings=_Tiny, size=1)  # metadata lies
    assert out["error"] == "too_large"


@pytest.mark.asyncio
async def test_corrupt_pdf() -> None:
    raw = (FIX / "contract_sample.pdf").read_bytes()
    out = await _call(raw[: len(raw) // 2])
    assert out["ok"] is False
    assert out["error"] == "unreadable"


@pytest.mark.asyncio
async def test_truncation() -> None:
    out = await _call((FIX / "contract_sample.pdf").read_bytes(), max_chars=5)
    assert out["ok"] is True
    assert out["truncated"] is True
    assert len(out["text"]) == 5


@pytest.mark.asyncio
async def test_graph_error_passthrough() -> None:
    import httpx

    c = AsyncMock()
    resp = httpx.Response(404, text="nope", request=httpx.Request("GET", "https://graph.microsoft.com/x"))
    c.get_attachment = AsyncMock(side_effect=httpx.HTTPStatusError("e", request=resp.request, response=resp))
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=c),
    ):
        out = json.loads(await email_reader.get_attachment_text("m1", "a1", ctx=None))
    assert out["error"] == "http_error"
    assert out["status_code"] == 404


def _multipage(n: int, encrypt_user_pw: str | None = None, alg: str = "AES-128") -> bytes:
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    for i in range(n):
        w.add_blank_page(612, 792)
    out = io.BytesIO()
    if encrypt_user_pw is not None:
        w.encrypt(encrypt_user_pw, "owner", algorithm=alg)
    w.write(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_non_file_attachment_is_not_pdf_without_metadata() -> None:
    c = AsyncMock()
    c.get_attachment = AsyncMock(
        return_value={"@odata.type": "#microsoft.graph.itemAttachment", "id": "a1", "name": "SecretName.msg"}
    )
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=c),
    ):
        raw = await email_reader.get_attachment_text("m1", "a1", ctx=None)
    assert json.loads(raw) == {"ok": False, "error": "not_pdf"}
    assert "SecretName" not in raw


@pytest.mark.asyncio
async def test_http_error_has_no_body_text() -> None:
    import httpx

    c = AsyncMock()
    req = httpx.Request("GET", "https://graph.microsoft.com/x")
    resp = httpx.Response(404, text="attachment SecretName.pdf not found", request=req)
    c.get_attachment = AsyncMock(side_effect=httpx.HTTPStatusError("e", request=req, response=resp))
    with (
        patch("outlook_mcp.tools.email_reader.get_settings", return_value=_S()),
        patch("outlook_mcp.tools.email_reader.make_graph_client", return_value=c),
    ):
        raw = await email_reader.get_attachment_text("m1", "a1", ctx=None)
    assert json.loads(raw) == {"error": "http_error", "status_code": 404}


class _TwoPages(_S):
    attachment_text_max_pages = 2


@pytest.mark.asyncio
async def test_page_cap_truncates_and_reports_document_pages() -> None:
    out = await _call(_multipage(5), settings=_TwoPages)
    assert out["ok"] is True
    assert out["pages"] == 5
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_multipage_char_truncation_stops_early() -> None:
    out = await _call(_multipage(3), max_chars=1)
    assert out["pages"] == 3


@pytest.mark.asyncio
async def test_max_chars_clamped_to_at_least_one() -> None:
    out = await _call((FIX / "contract_sample.pdf").read_bytes(), max_chars=-5)
    assert out["ok"] is True
    assert len(out["text"]) == 1
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_timeout_returns_unreadable() -> None:
    import time

    class _Fast(_S):
        attachment_text_timeout_seconds = 0.05

    def slow(*a, **k):
        time.sleep(0.3)
        return 1, "x", False

    with patch("outlook_mcp.tools.email_reader._extract_pdf_text", slow):
        out = await _call((FIX / "contract_sample.pdf").read_bytes(), settings=_Fast)
    assert out["error"] == "unreadable"


@pytest.mark.asyncio
async def test_encrypted_empty_password_is_readable() -> None:
    out = await _call(_multipage(1, encrypt_user_pw="", alg="AES-128"))
    assert out["ok"] is True
    assert out["pages"] == 1


@pytest.mark.asyncio
async def test_encrypted_with_user_password_is_unreadable() -> None:
    out = await _call(_multipage(1, encrypt_user_pw="s3cret"))
    assert out["error"] == "unreadable"


@pytest.mark.asyncio
async def test_dependency_error_maps_to_unreadable() -> None:
    from pypdf.errors import DependencyError

    def boom(*a, **k):
        raise DependencyError("cryptography is required for AES")

    with patch("outlook_mcp.tools.email_reader._extract_pdf_text", boom):
        out = await _call((FIX / "contract_sample.pdf").read_bytes())
    assert out["error"] == "unreadable"


@pytest.mark.asyncio
async def test_pypdf_warnings_do_not_reach_logs(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from outlook_mcp.server import build_mcp

    build_mcp()
    raw = (FIX / "contract_sample.pdf").read_bytes()
    broken = raw.replace(b"startxref\n", b"startxref\n9", 1).replace(b"%%EOF", b"")
    caplog.set_level(logging.DEBUG)
    await _call(broken)
    assert [r for r in caplog.records if r.name.startswith("pypdf") and r.levelno >= logging.WARNING] == []


# --- bounded extraction pool (stuck PDFs cannot starve other work) -------------------------------


@pytest.mark.asyncio
async def test_extraction_runs_on_dedicated_bounded_pool() -> None:
    import threading

    names: list[str] = []

    def record(*a, **k):
        names.append(threading.current_thread().name)
        return 1, "x", False

    with patch("outlook_mcp.tools.email_reader._extract_pdf_text", record):
        out = await _call((FIX / "contract_sample.pdf").read_bytes())
    assert out["ok"] is True
    assert names and names[0].startswith("pdf-text")
    assert email_reader._PDF_EXECUTOR._max_workers == 2


@pytest.mark.asyncio
async def test_stuck_extractions_hold_slots_and_do_not_pile_up() -> None:
    import asyncio
    import threading
    import time

    class _Fast(_S):
        attachment_text_timeout_seconds = 0.1

    release = threading.Event()
    started: list[float] = []

    def stuck(*a, **k):
        started.append(time.monotonic())
        release.wait(5)
        return 1, "x", False

    # Earlier tests may leave a slow extraction finishing on the shared pool: wait until both workers
    # are free at the same time (the barrier only passes with two concurrent idle workers).
    barrier = threading.Barrier(2, timeout=5)
    for f in [email_reader._PDF_EXECUTOR.submit(barrier.wait) for _ in range(2)]:
        f.result(timeout=5)

    raw = (FIX / "contract_sample.pdf").read_bytes()
    try:
        with patch("outlook_mcp.tools.email_reader._extract_pdf_text", stuck):
            first = await asyncio.gather(_call(raw, settings=_Fast), _call(raw, settings=_Fast))
            assert [o["error"] for o in first] == ["unreadable", "unreadable"]
            assert len(started) == 2
            # Both slots are still held by the running threads: a third call times out waiting
            # for a slot and never reaches the extractor.
            t0 = time.monotonic()
            third = await _call(raw, settings=_Fast)
            assert third["error"] == "unreadable"
            assert time.monotonic() - t0 < 1.0
            assert len(started) == 2
            # The default to_thread pool is untouched by the stuck extractions.
            assert await asyncio.wait_for(asyncio.to_thread(lambda: 42), timeout=1.0) == 42
            # Once the threads finish, the slots come back.
            release.set()
            await asyncio.sleep(0.2)
            fourth = await _call(raw, settings=_S)
            assert fourth["ok"] is True
            assert len(started) == 3
    finally:
        release.set()
