"""Pydantic models for mail and classification outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EmailAddress(BaseModel):
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
    from_: EmailAddress | None = Field(None, alias="from")
    sender: EmailAddress | None = None
    to_recipients: list[EmailAddress] = Field(default_factory=list)
    is_read: bool | None = None
    has_attachments: bool | None = None
    categories: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class EmailThreadSummary(BaseModel):
    conversation_id: str
    messages: list[EmailMessage]


class ClassificationIntent(BaseModel):
    customer_statement: str = ""
    required_action: str = ""
    urgency: str = "LOW"


class ExtractedData(BaseModel):
    promised_date: str | None = None
    disputed_amount: float | None = None
    invoice_numbers: list[str] = Field(default_factory=list)
    payment_reference: str | None = None


class ClassificationResult(BaseModel):
    email_id: str
    category: str
    confidence: float
    intent: ClassificationIntent
    reasoning: str = ""
    extracted_data: ExtractedData = Field(default_factory=ExtractedData)
    escalation: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    email_id: str
    invoice_numbers: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    payment_reference: str | None = None
    raw_notes: str = ""
