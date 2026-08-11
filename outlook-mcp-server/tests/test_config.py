"""Settings parsing (classification taxonomy)."""

from __future__ import annotations

from outlook_mcp.config import Settings


def test_classification_category_set_adds_unclassified_when_omitted() -> None:
    s = Settings(classification_categories="ALPHA,BETA")
    cats = s.classification_category_set()
    assert cats == frozenset({"ALPHA", "BETA", "UNCLASSIFIED"})


def test_classification_category_set_trims_whitespace() -> None:
    s = Settings(classification_categories=" FOO , BAR ")
    assert s.classification_category_set() == frozenset({"FOO", "BAR", "UNCLASSIFIED"})


def test_classification_category_set_unclassified_still_present_when_listed() -> None:
    s = Settings(classification_categories="ONLY_ONE,UNCLASSIFIED")
    assert s.classification_category_set() == frozenset({"ONLY_ONE", "UNCLASSIFIED"})


def test_default_taxonomy_includes_agreement_categories() -> None:
    s = Settings()
    cats = s.classification_category_set()
    assert "AGREEMENT_REACHED" in cats
    assert "AGREEMENT_SIGNED" in cats


def test_attachment_settings_defaults() -> None:
    s = Settings()
    assert s.max_attachment_upload_bytes == 150 * 1024 * 1024
    assert s.max_attachment_count == 10
    assert s.max_multimodal_attachment_bytes == 8 * 1024 * 1024


def test_attachment_settings_overridable() -> None:
    s = Settings(max_attachment_upload_bytes=1024, max_attachment_count=2, max_multimodal_attachment_bytes=512)
    assert s.max_attachment_upload_bytes == 1024
    assert s.max_attachment_count == 2
    assert s.max_multimodal_attachment_bytes == 512
