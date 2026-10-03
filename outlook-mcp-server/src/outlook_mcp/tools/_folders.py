"""Resolve a user-supplied folder reference (id, well-known name, display name or path) to a Graph id."""

from __future__ import annotations

import re
from typing import Any

from outlook_mcp.auth.graph_client import (
    WELL_KNOWN_MAIL_FOLDERS,
    GraphMailClient,
    MailFolderAmbiguousError,
    MailFolderNotFoundError,
)

# Exchange / outlook.com folder ids are long base64(url) strings (often 100+ chars) and may
# contain "/" — so "contains a slash" alone cannot tell an id from a path like "Auto/DMARC".
_GRAPH_ID_RE = re.compile(r"[A-Za-z0-9+/=_\-.]{60,}")


def looks_like_graph_id(ref: str) -> bool:
    return bool(_GRAPH_ID_RE.fullmatch(ref.strip()))


async def resolve_folder_reference(
    client: GraphMailClient, ref: str, *, require_id: bool = False
) -> str:
    """Return a value usable as a Graph folder id for ``ref``.

    Accepted forms, checked in order:

    1. Well-known name (``inbox``, ``archive``, ``deleteditems``, ...). Returned as-is unless
       ``require_id`` is true (inbox rules' ``moveToFolder`` needs a real id), in which case
       it is looked up.
    2. A Graph folder id (long, no spaces) — returned unchanged.
    3. A path ``"Parent/Child"`` — walked segment by segment.
    4. A display name — resolved anywhere in the tree (must be unique).

    Raises ``MailFolderNotFoundError`` / ``MailFolderAmbiguousError`` / ``ValueError``.
    """
    value = (ref or "").strip()
    if not value:
        raise ValueError("folder reference must be a non-empty string")
    if value.casefold() in WELL_KNOWN_MAIL_FOLDERS:
        if not require_id:
            return value
        folder = await client.get_mail_folder(value)
        return folder.get("id") or value
    if looks_like_graph_id(value):
        return value
    if "/" in value:
        return await client.resolve_mail_folder_path(value)
    return await client.resolve_mail_folder_id_by_display_name(value)


def folder_error_payload(e: Exception, **extra: Any) -> dict[str, Any]:
    """Tool error JSON for folder resolution failures (same shape as ``create_mail_folder``)."""
    if isinstance(e, MailFolderNotFoundError):
        return {"error": "folder_not_found", "message": str(e), "folder_name": e.display_name, **extra}
    if isinstance(e, MailFolderAmbiguousError):
        return {
            "error": "folder_ambiguous",
            "message": str(e),
            "folder_name": e.display_name,
            "match_count": e.match_count,
            **extra,
        }
    return {"error": "validation_error", "message": str(e), **extra}


FOLDER_RESOLUTION_ERRORS = (MailFolderNotFoundError, MailFolderAmbiguousError, ValueError)
