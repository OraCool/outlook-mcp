"""Shared helper tests."""

from __future__ import annotations

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
