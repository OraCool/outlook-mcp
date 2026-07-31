"""Document-scoped anonymization with restore (presidio-anonymizer path)."""

from __future__ import annotations

import pytest

from outlook_mcp.pii.redactor import (
    PseudonymMap,
    anonymize_email_json,
    is_presidio_available,
    redact_text,
    restore_text,
)

pytestmark = pytest.mark.skipif(not is_presidio_available(), reason="presidio not installed")

_ENTITIES = "PERSON,EMAIL_ADDRESS,LOCATION,PHONE_NUMBER"


def test_same_value_gets_same_placeholder_across_separate_calls() -> None:
    """The bug that motivated this: a per-call counter gave two different people the same label."""
    m = PseudonymMap()
    a = redact_text("John Smith", strategy="pseudonymize", allowed_entities={"PERSON"}, mapping=m)
    b = redact_text("Mary Jones", strategy="pseudonymize", allowed_entities={"PERSON"}, mapping=m)
    assert a != b, "distinct people must not collapse to the same placeholder"

    # ...and the same person must keep their placeholder on a later, separate call.
    a_again = redact_text("John Smith", strategy="pseudonymize", allowed_entities={"PERSON"}, mapping=m)
    assert a_again == a


def test_restore_recovers_the_original_text() -> None:
    m = PseudonymMap()
    red = redact_text(
        "Contact John Smith at john@acme.com",
        strategy="pseudonymize",
        allowed_entities={"PERSON", "EMAIL_ADDRESS"},
        mapping=m,
    )
    assert "John Smith" not in red
    assert "john@acme.com" not in red
    assert restore_text(red, m) == "Contact John Smith at john@acme.com"


def test_restore_rewrites_placeholders_inside_model_output() -> None:
    """A draft written *about* the redacted email must come back with real values."""
    m = PseudonymMap()
    redact_text("John Smith", strategy="pseudonymize", allowed_entities={"PERSON"}, mapping=m)
    ph = next(iter(m.placeholders))
    assert restore_text(f"Dear {ph}, thanks for your note.", m) == "Dear John Smith, thanks for your note."


def test_restore_is_not_confused_by_shared_placeholder_prefixes() -> None:
    """[PERSON_1] must not match inside [PERSON_10]; restore has to prefer the longest label."""
    m = PseudonymMap()
    for i in range(12):
        m.placeholder_for("PERSON", f"Person Number {i}")
    p1 = m.placeholder_for("PERSON", "Person Number 1")
    p10 = m.placeholder_for("PERSON", "Person Number 10")
    assert restore_text(f"{p10} and {p1}", m) == "Person Number 10 and Person Number 1"


def test_anonymize_email_json_shares_one_map_across_all_fields() -> None:
    email = {
        "subject": "Invoice for John Smith",
        "body_preview": "John Smith asked about the invoice.",
        "from": {"address": "john@acme.com", "name": "John Smith"},
        "to_recipients": [{"address": "billing@corp.com", "name": "Billing Team"}],
    }
    red, m = anonymize_email_json(email, strategy="pseudonymize", entities_csv=_ENTITIES)

    assert "John Smith" not in str(red)
    assert "john@acme.com" not in str(red)

    # One person, one placeholder — in the subject, the preview and the address blob alike.
    ph = m.placeholder_for("PERSON", "John Smith")
    assert ph in red["subject"]
    assert ph in red["body_preview"]
    assert red["from"]["name"] == ph


def test_anonymize_email_json_leaves_the_input_untouched() -> None:
    email = {"subject": "Invoice for John Smith", "from": {"address": "john@acme.com", "name": "John Smith"}}
    before = str(email)
    anonymize_email_json(email, strategy="pseudonymize", entities_csv=_ENTITIES)
    assert str(email) == before


def test_disabled_entities_are_left_alone() -> None:
    _red, m = anonymize_email_json(
        {"subject": "Call John Smith"},
        strategy="pseudonymize",
        entities_csv="CREDIT_CARD",
    )
    assert m.placeholders == set()
