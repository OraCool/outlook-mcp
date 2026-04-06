"""Tests for untrusted-email prompt helpers."""

from __future__ import annotations

from outlook_mcp.tools._email_prompt import (
    BEGIN_UNTRUSTED_EMAIL_JSON,
    build_untrusted_email_user_text,
    sanitize_email_json_for_prompt,
)


def test_build_untrusted_email_user_text_contains_markers_and_id() -> None:
    payload = {"id": "m1", "subject": "x"}
    text = build_untrusted_email_user_text("m1", payload)
    assert "authoritative_message_id: m1" in text
    assert BEGIN_UNTRUSTED_EMAIL_JSON in text
    assert "---END_UNTRUSTED_EMAIL_JSON---" in text
    assert '"subject": "x"' in text


def test_sanitize_truncates_long_subject() -> None:
    long_sub = "S" * 2000
    out = sanitize_email_json_for_prompt({"subject": long_sub}, max_subject=100)
    assert len(out["subject"]) <= 120  # includes truncation suffix
    assert "truncated" in out["subject"]


def test_sanitize_strips_html_body() -> None:
    raw = {
        "body_content_type": "html",
        "body_content": '<p>Hello</p><script>evil()</script><style>x{}</style>',
    }
    out = sanitize_email_json_for_prompt(raw)
    assert "script" not in out["body_content"].lower()
    assert "Hello" in out["body_content"]
