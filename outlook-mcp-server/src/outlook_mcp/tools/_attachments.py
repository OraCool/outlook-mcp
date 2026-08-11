"""Attachment input validation, decoding, and Graph payload helpers.

Shared by ``email_writer.py`` (attaching files to outgoing/draft messages) and
``email_reader.py`` (downloading an existing attachment's bytes).
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from outlook_mcp.auth.graph_client import GraphMailClient

# Graph's documented ceiling for attachments embedded directly in a message payload
# (``sendMail`` / ``POST /messages``). Above this, an upload session is required.
SMALL_ATTACHMENT_THRESHOLD_BYTES = 3 * 1024 * 1024


class AttachmentInput(BaseModel):
    """Validated shape of one entry in a tool's ``attachments`` argument."""

    filename: str
    content_type: str | None = None
    content_base64: str
    is_inline: bool = False
    content_id: str | None = None


def parse_attachment_inputs(raw: list[dict[str, Any]] | None) -> list[AttachmentInput]:
    """Validate/normalize tool-argument attachment dicts. Raises ``ValueError`` on bad shape."""
    if not raw:
        return []
    try:
        return [AttachmentInput.model_validate(item) for item in raw]
    except ValidationError as e:
        raise ValueError(f"Invalid attachment: {e}") from e


def decode_attachment_base64(content_base64: str) -> bytes:
    """Decode base64 attachment content. Raises ``ValueError`` on malformed input."""
    try:
        return base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"Invalid base64 attachment content: {e}") from e


def guess_content_type(filename: str, declared: str | None) -> str:
    """``declared`` if set, else sniffed from ``filename``'s extension, else a generic fallback."""
    if declared:
        return declared
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def validate_attachment_limits(attachments: list[AttachmentInput], *, max_count: int, max_bytes: int) -> None:
    """Raise ``ValueError`` if the attachment list violates count, size, or content rules."""
    if len(attachments) > max_count:
        raise ValueError(f"At most {max_count} attachments allowed per call, got {len(attachments)}.")
    for a in attachments:
        decoded = decode_attachment_base64(a.content_base64)
        if not decoded:
            raise ValueError(f"Attachment {a.filename!r} is empty.")
        if len(decoded) > max_bytes:
            raise ValueError(
                f"Attachment {a.filename!r} ({len(decoded)} bytes) exceeds the {max_bytes}-byte limit."
            )


def has_large_attachment(attachments: list[AttachmentInput]) -> bool:
    """True if any attachment's decoded size exceeds Graph's small-attachment threshold."""
    return any(len(decode_attachment_base64(a.content_base64)) > SMALL_ATTACHMENT_THRESHOLD_BYTES for a in attachments)


def build_inline_small_attachments_payload(attachments: list[AttachmentInput]) -> list[dict[str, Any]]:
    """Graph ``attachments`` array for embedding directly in a message payload (small files only)."""
    return [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": a.filename,
            "contentType": guess_content_type(a.filename, a.content_type),
            "contentBytes": a.content_base64,
            "isInline": a.is_inline,
        }
        for a in attachments
    ]


async def attach_files_to_message(
    client: GraphMailClient, message_id: str, attachments: list[AttachmentInput]
) -> list[dict[str, Any]]:
    """Attach each file to an existing message, routing small vs. large by decoded size."""
    results: list[dict[str, Any]] = []
    for a in attachments:
        content_type = guess_content_type(a.filename, a.content_type)
        decoded = decode_attachment_base64(a.content_base64)
        if len(decoded) <= SMALL_ATTACHMENT_THRESHOLD_BYTES:
            result = await client.add_attachment_small(
                message_id,
                name=a.filename,
                content_type=content_type,
                content_b64=a.content_base64,
                is_inline=a.is_inline,
            )
        else:
            result = await client.upload_large_attachment(
                message_id,
                name=a.filename,
                content_type=content_type,
                content_bytes=decoded,
                is_inline=a.is_inline,
            )
        results.append(result)
    return results
