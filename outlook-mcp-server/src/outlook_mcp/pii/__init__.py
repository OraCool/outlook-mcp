"""PII redaction helpers (optional Presidio dependency)."""

from __future__ import annotations

from outlook_mcp.pii.redactor import (
    PseudonymMap,
    anonymize_email_json,
    is_presidio_available,
    redact_email_json,
    redact_email_json_if_enabled,
    redact_text,
    restore_text,
)

__all__ = [
    "PseudonymMap",
    "anonymize_email_json",
    "is_presidio_available",
    "redact_email_json",
    "redact_email_json_if_enabled",
    "redact_text",
    "restore_text",
]
