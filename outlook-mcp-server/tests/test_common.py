"""Shared helper tests."""

from __future__ import annotations

from outlook_mcp.tools._common import parse_json_object


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
