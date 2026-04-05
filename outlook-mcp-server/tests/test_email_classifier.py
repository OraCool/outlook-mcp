"""Classification prompt content."""

from outlook_mcp.tools.email_classifier import CLASSIFICATION_SYSTEM


def test_classification_prompt_lists_categories() -> None:
    assert "INVOICE_DISPUTE" in CLASSIFICATION_SYSTEM
    assert "PAYMENT_PROMISE" in CLASSIFICATION_SYSTEM
    assert "UNCLASSIFIED" in CLASSIFICATION_SYSTEM
    assert "confidence" in CLASSIFICATION_SYSTEM
