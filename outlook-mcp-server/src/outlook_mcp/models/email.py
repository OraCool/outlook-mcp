"""Pydantic models for mail and classification outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_CLASSIFICATION_CATEGORIES: frozenset[str] = frozenset(
    {
        "PAYMENT_REMINDER_SENT",
        "INVOICE_NOT_RECEIVED",
        "INVOICE_DISPUTE",
        "PAYMENT_PROMISE",
        "PAYMENT_CONFIRMATION",
        "EXTENSION_REQUEST",
        "PARTIAL_PAYMENT_NOTE",
        "ESCALATION_LEGAL",
        "INTERNAL_NOTE",
        "UNCLASSIFIED",
        "REMITTANCE_ADVICE",
        "BALANCE_INQUIRY",
        "CREDIT_NOTE_REQUEST",
        "AUTO_REPLY",
        "BILLING_UPDATE",
    }
)


def get_classification_categories() -> frozenset[str]:
    """Active taxonomy from :func:`~outlook_mcp.config.get_settings` (env ``CLASSIFICATION_CATEGORIES``)."""
    from outlook_mcp.config import get_settings

    return get_settings().classification_category_set()


class EmailAddress(BaseModel):
    """SMTP address and optional display name from Graph ``recipient`` / ``from`` blobs."""

    address: str | None = None
    name: str | None = None


class EmailMessage(BaseModel):
    """Subset of Graph message fields returned by tools."""

    id: str
    subject: str | None = None
    body_preview: str | None = None
    body_content: str | None = None
    body_content_type: str | None = None
    received_date_time: str | None = None
    sent_date_time: str | None = None
    conversation_id: str | None = None
    internet_message_id: str | None = None
    from_: EmailAddress | None = Field(
        None,
        alias="from",
        description="Graph field ``from`` (Python attribute ``from_``).",
    )
    sender: EmailAddress | None = None
    to_recipients: list[EmailAddress] = Field(default_factory=list)
    is_read: bool | None = None
    has_attachments: bool | None = None
    categories: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class EmailThreadSummary(BaseModel):
    """Messages sharing the same Graph ``conversationId``."""

    conversation_id: str
    messages: list[EmailMessage]


class ClassificationIntent(BaseModel):
    """Structured intent slice inside a classifier JSON response."""

    customer_statement: str = Field(default="", max_length=4000)
    required_action: str = Field(default="", max_length=4000)
    urgency: str = Field(default="LOW", max_length=32)


class ExtractedData(BaseModel):
    """Invoice/payment-related fields parsed from classifier output."""

    promised_date: str | None = Field(default=None, max_length=64)
    disputed_amount: float | None = None
    invoice_numbers: list[str] = Field(default_factory=list)
    payment_reference: str | None = Field(default=None, max_length=512)


class ClassificationResult(BaseModel):
    """Single-label AR taxonomy classification for one message (MCP sampling output)."""

    email_id: str = Field(max_length=512)
    category: str = Field(max_length=128)
    confidence: float
    intent: ClassificationIntent = Field(default_factory=ClassificationIntent)
    reasoning: str = Field(default="", max_length=8000)
    extracted_data: ExtractedData = Field(default_factory=ExtractedData)
    escalation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_unknown_category(self) -> ClassificationResult:
        if self.category not in get_classification_categories():
            self.category = "UNCLASSIFIED"
            self.confidence = min(float(self.confidence), 0.74)
        return self


class ExtractionResult(BaseModel):
    """Structured fields extracted from an email body (MCP sampling / extractor tool)."""

    email_id: str = Field(max_length=512)
    invoice_numbers: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    payment_reference: str | None = Field(default=None, max_length=512)
    raw_notes: str = Field(default="", max_length=4000)

    @field_validator("invoice_numbers", "amounts", "dates", mode="after")
    @classmethod
    def cap_list_items(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for item in v[:50]:
            s = str(item) if item is not None else ""
            out.append(s[:256] if len(s) > 256 else s)
        return out
