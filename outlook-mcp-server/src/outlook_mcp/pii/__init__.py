"""PII redaction helpers (optional Presidio dependency)."""

from __future__ import annotations

from outlook_mcp.pii.redactor import (
    is_presidio_available,
    redact_email_json,
    redact_email_json_if_enabled,
    redact_text,
)

__all__ = [
    "is_presidio_available",
    "redact_email_json",
    "redact_email_json_if_enabled",
    "redact_text",
]
