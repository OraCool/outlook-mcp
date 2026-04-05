"""Structured extraction from email body via MCP sampling."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.types import SamplingMessage, TextContent

from outlook_mcp.auth.token_handler import GraphTokenExpiredError, GraphTokenMissingError
from outlook_mcp.models.email import ExtractionResult
from outlook_mcp.tools._common import (
    graph_message_to_model,
    make_graph_client,
    parse_json_object,
    tool_error_token,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

EXTRACTION_PROMPT = """Extract structured AR-relevant facts from the email. Respond with a single JSON object only:
{
  "email_id": "string",
  "invoice_numbers": ["string"],
  "amounts": ["string"],
  "dates": ["string"],
  "payment_reference": "string or null",
  "raw_notes": "short factual notes, no PII beyond what is in the email"
}
Do not invent invoice numbers or amounts; only extract what is explicitly present.
"""


async def extract_email_data(message_id: str, ctx: Context) -> str:
    """Fetch the message and use sampling to extract invoice numbers, amounts, dates, payment references."""
    try:
        g = make_graph_client(ctx)
        raw = await g.get_message(
            message_id,
            select="id,subject,bodyPreview,body,receivedDateTime,from,conversationId",
        )
        email = graph_message_to_model(raw)
        email_json = email.model_dump(mode="json", by_alias=True)
    except (GraphTokenExpiredError, GraphTokenMissingError) as e:
        return json.dumps(tool_error_token(e))
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": "fetch_failed", "message": str(e)})

    user_prompt = EXTRACTION_PROMPT + "\n\nEmail JSON:\n" + json.dumps(email_json, indent=2)

    try:
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=user_prompt),
                )
            ],
            max_tokens=1200,
            temperature=0,
        )
        text = getattr(result.content, "text", None) or ""
        raw_obj = parse_json_object(text)
        if raw_obj.get("email_id") != message_id:
            msg = "sampling email_id does not match requested message_id"
            raise ValueError(msg)
        parsed = ExtractionResult.model_validate(raw_obj)
        return json.dumps(
            {
                "sampling": True,
                "model": getattr(result, "model", None),
                "extraction": parsed.model_dump(mode="json"),
                "email": email_json,
            },
            indent=2,
        )
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {
                "sampling": False,
                "sampling_error": str(e),
                "hint": "Parse the email field in your orchestrator.",
                "email": email_json,
            },
            indent=2,
        )
