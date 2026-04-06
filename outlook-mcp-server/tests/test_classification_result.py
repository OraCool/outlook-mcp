"""ClassificationResult validation (output hardening)."""

from __future__ import annotations

from outlook_mcp.models.email import ClassificationResult


def test_unknown_category_coerced_to_unclassified() -> None:
    r = ClassificationResult.model_validate(
        {
            "email_id": "e1",
            "category": "ATTACKER_CATEGORY",
            "confidence": 0.99,
            "intent": {},
        }
    )
    assert r.category == "UNCLASSIFIED"
    assert r.confidence <= 0.74


def test_valid_category_unchanged() -> None:
    r = ClassificationResult.model_validate(
        {
            "email_id": "e1",
            "category": "PAYMENT_PROMISE",
            "confidence": 0.9,
            "intent": {},
        }
    )
    assert r.category == "PAYMENT_PROMISE"
    assert r.confidence == 0.9
