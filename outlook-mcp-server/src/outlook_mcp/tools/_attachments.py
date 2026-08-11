"""Attachment input validation, decoding, and Graph payload helpers.

Shared by ``email_writer.py`` (attaching files to outgoing/draft messages) and
``email_reader.py`` (downloading an existing attachment's bytes).
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError, model_validator

if TYPE_CHECKING:
    from outlook_mcp.auth.graph_client import GraphMailClient

# Graph's documented ceiling for attachments embedded directly in a message payload
# (``sendMail`` / ``POST /messages``). Above this, an upload session is required.
SMALL_ATTACHMENT_THRESHOLD_BYTES = 3 * 1024 * 1024


class AttachmentInput(BaseModel):
    """Validated shape of one entry in a tool's ``attachments`` argument.

    Content comes from exactly one of ``content_base64`` (the model transcribes the file
    inline — fine for small files, but forces the model to generate one output token per
    base64 character for anything large) or ``file_path`` (the server reads the file itself
    from local disk — the model just passes a path, no matter the file's size).
    """

    filename: str | None = None
    content_type: str | None = None
    content_base64: str | None = None
    file_path: str | None = None
    is_inline: bool = False
    content_id: str | None = None

    @model_validator(mode="after")
    def _validate_source_and_filename(self) -> "AttachmentInput":
        if bool(self.content_base64) == bool(self.file_path):
            raise ValueError("Exactly one of content_base64 or file_path must be provided.")
        if not self.filename:
            if self.file_path:
                self.filename = Path(self.file_path).name
            else:
                raise ValueError("filename is required when content_base64 is used.")
        return self


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


def read_attachment_file_bytes(file_path: str) -> bytes:
    """Read attachment bytes from local disk. Raises ``ValueError`` if missing/unreadable."""
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise ValueError(f"Attachment file not found: {file_path!r}")
    try:
        return path.read_bytes()
    except OSError as e:
        raise ValueError(f"Could not read attachment file {file_path!r}: {e}") from e


def resolve_attachment_bytes(a: AttachmentInput) -> bytes:
    """Decoded content for an attachment, from whichever source (``content_base64``/``file_path``) it uses."""
    if a.file_path:
        return read_attachment_file_bytes(a.file_path)
    assert a.content_base64 is not None  # enforced by AttachmentInput's validator
    return decode_attachment_base64(a.content_base64)


def validate_attachment_limits(attachments: list[AttachmentInput], *, max_count: int, max_bytes: int) -> None:
    """Raise ``ValueError`` if the attachment list violates count, size, or content rules."""
    if len(attachments) > max_count:
        raise ValueError(f"At most {max_count} attachments allowed per call, got {len(attachments)}.")
    for a in attachments:
        decoded = resolve_attachment_bytes(a)
        if not decoded:
            raise ValueError(f"Attachment {a.filename!r} is empty.")
        if len(decoded) > max_bytes:
            raise ValueError(
                f"Attachment {a.filename!r} ({len(decoded)} bytes) exceeds the {max_bytes}-byte limit."
            )


def has_large_attachment(attachments: list[AttachmentInput]) -> bool:
    """True if any attachment's decoded size exceeds Graph's small-attachment threshold."""
    return any(len(resolve_attachment_bytes(a)) > SMALL_ATTACHMENT_THRESHOLD_BYTES for a in attachments)


def build_inline_small_attachments_payload(attachments: list[AttachmentInput]) -> list[dict[str, Any]]:
    """Graph ``attachments`` array for embedding directly in a message payload (small files only)."""
    result = []
    for a in attachments:
        assert a.filename is not None  # enforced by AttachmentInput's validator
        result.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a.filename,
                "contentType": guess_content_type(a.filename, a.content_type),
                "contentBytes": base64.b64encode(resolve_attachment_bytes(a)).decode(),
                "isInline": a.is_inline,
            }
        )
    return result


async def attach_files_to_message(
    client: GraphMailClient, message_id: str, attachments: list[AttachmentInput]
) -> list[dict[str, Any]]:
    """Attach each file to an existing message, routing small vs. large by decoded size."""
    results: list[dict[str, Any]] = []
    for a in attachments:
        assert a.filename is not None  # enforced by AttachmentInput's validator
        content_type = guess_content_type(a.filename, a.content_type)
        decoded = resolve_attachment_bytes(a)
        if len(decoded) <= SMALL_ATTACHMENT_THRESHOLD_BYTES:
            result = await client.add_attachment_small(
                message_id,
                name=a.filename,
                content_type=content_type,
                content_b64=base64.b64encode(decoded).decode(),
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
