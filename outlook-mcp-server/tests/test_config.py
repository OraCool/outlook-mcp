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
