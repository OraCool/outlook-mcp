"""Email classification via MCP sampling (client-side LLM)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import SamplingMessage, TextContent

from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.tools._common import graph_message_to_model, make_graph_client, tool_error_token

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

# Aligned with ar-mail-management/prompts/EmailClassifier.md output taxonomy
CLASSIFICATION_SYSTEM = """You are an AR Email Classification Specialist. Classify the email into exactly one category.

Allowed categories (use the exact string):
PAYMENT_REMINDER_SENT, INVOICE_NOT_RECEIVED, INVOICE_DISPUTE, PAYMENT_PROMISE, PAYMENT_CONFIRMATION,
EXTENSION_REQUEST, PARTIAL_PAYMENT_NOTE, ESCALATION_LEGAL, INTERNAL_NOTE, UNCLASSIFIED, REMITTANCE_ADVICE,
BALANCE_INQUIRY, CREDIT_NOTE_REQUEST, AUTO_REPLY, BILLING_UPDATE

Rules:
- If confidence in the best category is below 0.75, use UNCLASSIFIED.
- Respond with a single JSON object only (no markdown), matching this schema:
{
  "email_id": "string",
  "category": "<one of the allowed categories>",
  "confidence": 0.0,
  "intent": {
    "customer_statement": "string (use [CUSTOMER], [AMOUNT], [DATE] placeholders instead of raw PII in this field)",
    "required_action": "string",
    "urgency": "LOW|MEDIUM|HIGH|CRITICAL"
  },
  "reasoning": "string (use placeholders for PII)",
  "extracted_data": {
    "promised_date": "ISO8601 date or null",
    "disputed_amount": number or null,
    "invoice_numbers": ["string"],
    "payment_reference": "string or null"
  },
  "escalation": { "required": false, "reason": "string or null" }
}
"""


async def categorize_email(message_id: str, ctx: Context) -> str:
    """Load the message from Graph, then ask the host LLM (sampling) to classify it.

    If the client does not support sampling, returns the email JSON plus a note to classify upstream.
    """
    try:
        client = await make_graph_client(ctx)
        raw = await client.get_message(
            message_id,
            select=(
                "id,subject,bodyPreview,body,receivedDateTime,from,sender,toRecipients,"
                "conversationId,categories"
            ),
        )
        email = graph_message_to_model(raw)
        email_json = email.model_dump(mode="json", by_alias=True)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": "fetch_failed", "message": str(e)})

    user_prompt = (
        CLASSIFICATION_SYSTEM
        + "\n\nEmail payload (JSON):\n"
        + json.dumps(email_json, indent=2)
        + "\n\nReturn only the classification JSON. email_id must equal the input id."
    )

    try:
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=user_prompt),
                )
            ],
            max_tokens=2000,
            temperature=0,
        )
        text = getattr(result.content, "text", None) or ""
        return json.dumps(
            {
                "sampling": True,
                "model": getattr(result, "model", None),
                "classification_text": text,
                "email": email_json,
            },
            indent=2,
        )
    except Exception as e:  # noqa: BLE001 — client may not support sampling
        return json.dumps(
            {
                "sampling": False,
                "sampling_error": str(e),
                "hint": "Classify this email using the EmailClassifier assistant in CodeMie.",
                "email": email_json,
            },
            indent=2,
        )
