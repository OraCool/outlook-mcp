"""Shared helper tests."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from mcp.types import CreateMessageResult, TextContent

from outlook_mcp.tools._common import parse_json_object, sampling_response_text


def test_parse_json_object_plain() -> None:
    parsed = parse_json_object('{"email_id":"1","category":"UNCLASSIFIED"}')
    assert parsed["email_id"] == "1"
    assert parsed["category"] == "UNCLASSIFIED"


def test_parse_json_object_fenced_json() -> None:
    text = """```json
{"email_id":"2","invoice_numbers":["INV-1"]}
```"""
    parsed = parse_json_object(text)
    assert parsed["email_id"] == "2"
    assert parsed["invoice_numbers"] == ["INV-1"]


def test_parse_json_object_preamble_and_fence() -> None:
    text = """Here is the classification:
```json
{"email_id":"3","category":"AUTO_REPLY","confidence":0.9}
```
Thanks."""
    parsed = parse_json_object(text)
    assert parsed["email_id"] == "3"
    assert parsed["category"] == "AUTO_REPLY"


def test_parse_json_object_preamble_raw_json() -> None:
    text = 'Sure.\n{"email_id":"4","category":"UNCLASSIFIED","confidence":0.5}'
    parsed = parse_json_object(text)
    assert parsed["email_id"] == "4"


def test_parse_json_object_braces_inside_string() -> None:
    text = '{"email_id":"5","reasoning":"use {curly} in text","confidence":0.8}'
    parsed = parse_json_object(text)
    assert parsed["email_id"] == "5"
    assert "{curly}" in parsed["reasoning"]


def test_sampling_response_text_single_textcontent() -> None:
    r = CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text='{"a":1}'),
        model="m",
    )
    assert sampling_response_text(r) == '{"a":1}'


def test_sampling_response_text_list_of_blocks() -> None:
    r = MagicMock()
    r.content = [
        TextContent(type="text", text='{"email_id": "x"'),
        TextContent(type="text", text=', "category": "UNCLASSIFIED"}'),
    ]
    assert sampling_response_text(r) == '{"email_id": "x"\n, "category": "UNCLASSIFIED"}'


def test_sampling_response_text_dict_text_blocks() -> None:
    """Wire-style content blocks (e.g. some MCP clients) as plain dicts."""
    r = MagicMock()
    r.content = [
        {"type": "text", "text": '{"email_id": "y"'},
        {"type": "text", "text": ', "category": "UNCLASSIFIED"}'},
    ]
    assert sampling_response_text(r) == '{"email_id": "y"\n, "category": "UNCLASSIFIED"}'


def test_parse_json_object_empty_raises() -> None:
    with pytest.raises(ValueError, match="Empty model response from MCP sampling"):
        parse_json_object("")
    with pytest.raises(ValueError, match="Empty model response from MCP sampling"):
        parse_json_object("   \n\t  ")


def test_parse_json_object_no_brace_includes_preview() -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_json_object("Not JSON at all")
    assert "no `{` character" in str(exc_info.value)
    assert "Preview:" in str(exc_info.value)
    assert "Not JSON at all" in str(exc_info.value)


def test_parse_json_object_no_brace_omits_preview_for_body_content_marker() -> None:
    raw = "The assistant echoed body_content without JSON braces"
    with pytest.raises(ValueError) as exc_info:
        parse_json_object(raw)
    assert "Preview:" not in str(exc_info.value)


def test_parse_json_object_no_brace_omits_preview_when_too_long() -> None:
    raw = "x" * 400
    with pytest.raises(ValueError) as exc_info:
        parse_json_object(raw)
    assert "Preview:" not in str(exc_info.value)


def test_parse_json_object_invalid_json_includes_preview_when_safe() -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_json_object('{"broken": ')
    msg = str(exc_info.value)
    assert "No valid JSON object found" in msg
    assert "Preview:" in msg


def test_parse_json_object_invalid_json_omits_preview_for_long_response() -> None:
    raw = "{" + ("x" * 300)
    with pytest.raises(ValueError) as exc_info:
        parse_json_object(raw)
    assert "Preview:" not in str(exc_info.value)
