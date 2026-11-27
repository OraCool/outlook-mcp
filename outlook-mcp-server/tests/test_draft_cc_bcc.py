"""create_draft: cc/bcc recipients (validation, Graph payload, response counts, no addresses in logs)."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest

from outlook_mcp.tools.email_writer import create_draft


class _Enabled:
    enable_write_operations = True
    max_attachment_count = 10
    max_attachment_upload_bytes = 150 * 1024 * 1024


MARKER = "marker.secret@contoso.example"


async def _run(**kwargs):
    client = AsyncMock()
    client.create_message_draft = AsyncMock(return_value={"id": "d1"})
    with patch("outlook_mcp.tools.email_writer.get_settings", return_value=_Enabled()):
        with patch("outlook_mcp.tools.email_writer.make_graph_client", return_value=client):
            raw = await create_draft(ctx=None, subject="S", body_text="B", **kwargs)
    return json.loads(raw), client


def _addr(r: dict) -> str:
    return r["emailAddress"]["address"]


@pytest.mark.asyncio
async def test_cc_bcc_in_graph_payload_and_counts() -> None:
    data, client = await _run(
        to_addresses=["to@contoso.example"],
        cc_addresses=["cc1@contoso.example", " cc2@contoso.example "],
        bcc_addresses=["bcc@contoso.example"],
    )
    payload = client.create_message_draft.call_args[0][0]
    assert [_addr(r) for r in payload["toRecipients"]] == ["to@contoso.example"]
    assert [_addr(r) for r in payload["ccRecipients"]] == ["cc1@contoso.example", "cc2@contoso.example"]
    assert [_addr(r) for r in payload["bccRecipients"]] == ["bcc@contoso.example"]
    assert data["ok"] is True and data["message"]["id"] == "d1"
    assert data["cc_count"] == 2 and data["bcc_count"] == 1


@pytest.mark.asyncio
async def test_bcc_only_draft_allowed() -> None:
    data, client = await _run(bcc_addresses=["a@contoso.example", "b@contoso.example"])
    payload = client.create_message_draft.call_args[0][0]
    assert "toRecipients" not in payload and "ccRecipients" not in payload
    assert len(payload["bccRecipients"]) == 2
    assert data["cc_count"] == 0 and data["bcc_count"] == 2


@pytest.mark.asyncio
async def test_no_cc_bcc_keeps_payload_clean() -> None:
    data, client = await _run(to_addresses=["to@contoso.example"])
    payload = client.create_message_draft.call_args[0][0]
    assert "ccRecipients" not in payload and "bccRecipients" not in payload
    assert data["cc_count"] == 0 and data["bcc_count"] == 0


@pytest.mark.asyncio
async def test_dedupe_case_insensitive_within_list() -> None:
    data, client = await _run(
        cc_addresses=["A@Contoso.example", "a@contoso.example", "b@contoso.example"],
        bcc_addresses=["A@contoso.example"],
    )
    payload = client.create_message_draft.call_args[0][0]
    assert [_addr(r) for r in payload["ccRecipients"]] == ["A@Contoso.example", "b@contoso.example"]
    assert len(payload["bccRecipients"]) == 1  # same address across lists is not collapsed
    assert data["cc_count"] == 2 and data["bcc_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["cc_addresses", "bcc_addresses"])
@pytest.mark.parametrize(
    "bad",
    [
        "no-at-sign.example",
        "two@@contoso.example",
        "a@b@contoso.example",
        "@contoso.example",
        "local@nodot",
        "",
        "   ",
        "with space@contoso.example",
        "ctrl\x00char@contoso.example",
        "line\nbreak@contoso.example",
        "tab\t@contoso.example",
        "zero\u200bwidth@contoso.example",
        "bidi\u202eevil@contoso.example",
        "a<b@contoso.example",
        "a>b@contoso.example",
        "a,b@contoso.example",
        "a;b@contoso.example",
        'a"b@contoso.example',
        "a(b@contoso.example",
        "a)b@contoso.example",
        "local@.contoso.example",
        "local@contoso.example.",
        "local@contoso..example",
    ],
)
async def test_invalid_address_rejected_without_echo(field: str, bad: str) -> None:
    data, client = await _run(**{field: [MARKER, bad, "ok@contoso.example"]})
    assert data["error"] == "validation_error"
    assert data["field"] == field
    assert "1" in data["message"] and field in data["message"]
    serialized = json.dumps(data)
    assert MARKER not in serialized and "ok@contoso.example" not in serialized
    if bad.strip():
        assert bad not in serialized
        assert json.dumps(bad)[1:-1] not in serialized  # escaped form (\\t, \\n, \\u0000 ...)
    client.create_message_draft.assert_not_called()


@pytest.mark.asyncio
async def test_bad_entry_count_reported() -> None:
    data, _ = await _run(bcc_addresses=["bad1", "bad2", "good@contoso.example", "bad3"])
    assert data["field"] == "bcc_addresses"
    assert data["invalid_count"] == 3


@pytest.mark.asyncio
async def test_bad_entries_never_echoed_by_printable_marker() -> None:
    bads = ["BADMARK\t@contoso.example", "BADMARK\n@contoso.example", "BADMARK\x00@contoso.example"]
    data, _ = await _run(cc_addresses=bads)
    assert data["invalid_count"] == 3
    assert "BADMARK" not in json.dumps(data)


@pytest.mark.asyncio
async def test_both_lists_invalid_reports_both_counts() -> None:
    data, client = await _run(cc_addresses=["bad", "bad2"], bcc_addresses=["worse", "ok@contoso.example", "x y@contoso.example"])
    assert data["error"] == "validation_error"
    assert data["fields"] == {"cc_addresses": 2, "bcc_addresses": 2}
    assert data["field"] == "cc_addresses" and data["invalid_count"] == 2
    assert "ok@contoso.example" not in json.dumps(data)
    client.create_message_draft.assert_not_called()

    data, _ = await _run(cc_addresses=["ok@contoso.example"], bcc_addresses=["bad"])
    assert data["fields"] == {"bcc_addresses": 1} and data["field"] == "bcc_addresses"


@pytest.mark.asyncio
async def test_total_recipients_limit_500() -> None:
    to = [f"t{i}@contoso.example" for i in range(100)]
    bcc = [f"b{i}@contoso.example" for i in range(400)]
    data, client = await _run(to_addresses=to, bcc_addresses=bcc)
    assert data["ok"] is True and data["bcc_count"] == 400
    assert len(client.create_message_draft.call_args[0][0]["bccRecipients"]) == 400

    data, client = await _run(to_addresses=to, bcc_addresses=bcc + ["extra@contoso.example"])
    assert data["error"] == "validation_error"
    assert data["field"] == "recipients"
    assert "500" in data["message"]
    assert "extra@contoso.example" not in json.dumps(data)
    client.create_message_draft.assert_not_called()


@pytest.mark.asyncio
async def test_limit_counts_after_dedupe() -> None:
    bcc = [f"b{i}@contoso.example" for i in range(500)]
    data, _ = await _run(bcc_addresses=bcc + [bcc[0].upper()])
    assert data["ok"] is True and data["bcc_count"] == 500


@pytest.mark.asyncio
async def test_no_addresses_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    await _run(to_addresses=[MARKER], cc_addresses=[MARKER.replace("marker", "cc")], bcc_addresses=[MARKER.upper()])
    await _run(cc_addresses=[MARKER, "bad-" + MARKER + " x"])  # validation failure path
    leaked = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.INFO and ("contoso.example" in r.getMessage().lower() or "marker" in r.getMessage().lower())
    ]
    assert leaked == []
