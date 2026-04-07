"""Tests for PII redaction and response minimization (Presidio optional)."""

from __future__ import annotations

import pytest

import outlook_mcp.pii.redactor as redactor_mod
from outlook_mcp.pii.redactor import (
    is_presidio_available,
    redact_email_json,
    redact_text,
)
from outlook_mcp.tools._common import (
    email_json_for_tool_response,
    minimize_email_response,
    sanitize_client_error_message,
)


@pytest.fixture(autouse=True)
def _reset_presidio_singleton() -> None:
    redactor_mod._ANALYZER_ENGINE = None
    redactor_mod._PRESIDIO_UNAVAILABLE_LOGGED = False
    redactor_mod._DETERMINISTIC_RESPONSE_FALLBACK_LOGGED = False
    yield
    redactor_mod._ANALYZER_ENGINE = None


def test_minimize_email_response_strips_body() -> None:
    d = {
        "id": "m1",
        "subject": "Hi",
        "body_content": "SECRET BODY",
        "body_preview": "prev",
        "from": {"address": "a@b.com", "name": "A"},
    }
    m = minimize_email_response(d)
    assert "body_content" not in m
    assert m["id"] == "m1"
    assert m["from"]["address"] == "a@b.com"


def test_minimize_truncates_long_preview() -> None:
    long_prev = "x" * 600
    d = {"id": "1", "body_preview": long_prev}
    m = minimize_email_response(d)
    assert len(m["body_preview"]) <= 512
    assert m["body_preview"].endswith("...")


def test_sanitize_client_error_message_redacts_email() -> None:
    s = sanitize_client_error_message("failed for user@evil.com please")
    assert "user@evil.com" not in s
    assert "[EMAIL_REDACTED]" in s


def test_allowed_entities_for_script_cyrillic_drops_person_and_location() -> None:
    ru = "Просьба ознакомиться с представленными данными."
    eff = redactor_mod._allowed_entities_for_script(
        ru,
        {"PERSON", "LOCATION", "EMAIL_ADDRESS"},
    )
    assert eff == {"EMAIL_ADDRESS"}


def test_allowed_entities_for_script_english_keeps_person() -> None:
    eff = redactor_mod._allowed_entities_for_script(
        "Please contact John Smith about the invoice.",
        {"PERSON", "EMAIL_ADDRESS"},
    )
    assert eff == {"PERSON", "EMAIL_ADDRESS"}


@pytest.mark.skipif(not is_presidio_available(), reason="presidio optional extra")
def test_redact_text_russian_prose_no_false_person_labels() -> None:
    t = (
        "Просьба ознакомиться с представленными данными. После ознакомления прошу подписать документы."
    )
    out = redact_text(
        t,
        strategy="pseudonymize",
        allowed_entities={"PERSON", "EMAIL_ADDRESS", "LOCATION"},
    )
    assert "PERSON_" not in out
    assert out == t


def test_redact_email_json_disabled_returns_same_object() -> None:
    d = {"subject": "x"}
    out = redact_email_json(
        d,
        enabled=False,
        strategy="pseudonymize",
        entities_csv="EMAIL_ADDRESS",
    )
    assert out is d


def test_email_json_for_tool_response_full() -> None:
    class _S:
        pii_response_level = "full"
        pii_redaction_strategy = "pseudonymize"
        pii_entities = "EMAIL_ADDRESS"

    d = {"id": "1", "body_content": "x"}
    out = email_json_for_tool_response(d, _S())
    assert out["body_content"] == "x"


def test_email_json_for_tool_response_minimal() -> None:
    class _S:
        pii_response_level = "minimal"
        pii_redaction_strategy = "pseudonymize"
        pii_entities = "EMAIL_ADDRESS"

    d = {"id": "1", "subject": "s", "body_content": "BIG"}
    out = email_json_for_tool_response(d, _S())
    assert "body_content" not in out
    assert out["subject"] == "s"


@pytest.mark.skipif(not is_presidio_available(), reason="presidio optional extra")
def test_redact_text_pseudonymize_email() -> None:
    t = "Email: john@example.com thanks"
    out = redact_text(
        t,
        strategy="pseudonymize",
        allowed_entities={"EMAIL_ADDRESS"},
    )
    assert "john@example.com" not in out
    assert "EMAIL_ADDRESS" in out


@pytest.mark.skipif(not is_presidio_available(), reason="presidio optional extra")
def test_redact_text_remove_strategy() -> None:
    out = redact_text(
        "Contact a@b.co now",
        strategy="remove",
        allowed_entities={"EMAIL_ADDRESS"},
    )
    assert "a@b.co" not in out
    assert "[REDACTED]" in out


@pytest.mark.skipif(not is_presidio_available(), reason="presidio optional extra")
def test_redact_email_json_address_fields() -> None:
    d = {
        "subject": "Hello",
        "body_preview": "",
        "body_content": "",
        "from": {"address": "jane@contoso.org", "name": "Jane"},
        "sender": None,
        "to_recipients": [],
    }
    out = redact_email_json(
        d,
        enabled=True,
        strategy="pseudonymize",
        entities_csv="EMAIL_ADDRESS",
    )
    assert out["from"]["address"] != "jane@contoso.org"
    assert "contoso.org" not in out["from"]["address"]


def test_redact_email_json_deterministic_fallback_masks_email_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redactor_mod, "_get_analyzer", lambda: None)
    d = {
        "subject": "Hi from user@example.com",
        "body_preview": "Call lithuania2@leinonen.eu today",
        "from": {"address": "lithuania2@leinonen.eu", "name": "Leinonen Lithuania 2"},
        "to_recipients": [{"address": "z@z.com", "name": "Z"}],
    }
    out = redactor_mod.redact_email_json(
        d,
        enabled=True,
        strategy="pseudonymize",
        entities_csv="EMAIL_ADDRESS",
        deterministic_fallback=True,
    )
    blob = str(out)
    assert "example.com" not in blob
    assert "leinonen.eu" not in blob
    assert out["from"]["name"] == "[REDACTED]"
    assert out["from"]["address"] == "[EMAIL_REDACTED]"
    assert out["to_recipients"][0]["name"] == "[REDACTED]"


def test_email_json_for_tool_response_redacted_without_presidio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redactor_mod, "_get_analyzer", lambda: None)

    class _S:
        pii_response_level = "redacted"
        pii_redaction_strategy = "pseudonymize"
        pii_entities = "EMAIL_ADDRESS"

    d = {
        "id": "1",
        "subject": "mail user@example.com ok",
        "body_content": "should be omitted by minimal",
        "from": {"address": "user@example.com", "name": "Human"},
    }
    out = email_json_for_tool_response(d, _S())
    blob = str(out)
    assert "user@example.com" not in blob
    assert "body_content" not in out
    assert out["from"]["name"] == "[REDACTED]"


@pytest.mark.skipif(not is_presidio_available(), reason="presidio optional extra")
def test_email_json_for_tool_response_redacted() -> None:
    class _S:
        pii_response_level = "redacted"
        pii_redaction_strategy = "pseudonymize"
        pii_entities = "EMAIL_ADDRESS"

    d = {
        "id": "1",
        "subject": "mail user@example.com ok",
        "from": {"address": "user@example.com", "name": "X"},
    }
    out = email_json_for_tool_response(d, _S())
    blob = str(out)
    assert "user@example.com" not in blob
