"""Server ``instructions`` text generated from the tools that are actually registered."""

from __future__ import annotations

from collections.abc import Collection

APPEND_MAX_CHARS = 4000

_PURPOSE = (
    "Outlook / Microsoft Graph mail tools. The mailbox is fixed by the deployment (application mode) "
    "or is the signed-in user's (delegated mode)."
)

# (tools that gate the line: any registered -> include, text)
_LINES: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"search_emails"}),
        'search_emails: query is KQL, e.g. hasattachment:yes, from:addr, subject:"...", received:2026-01-01..2026-01-31. '
        "Results are eventually consistent; prefer read_filter / received_on / received_after / received_before "
        "over KQL date math.",
    ),
    (
        frozenset({"create_draft"}),
        "create_draft: put many recipients in bcc_addresses for group notices. The default response is compact "
        "(id and counts); nothing is sent.",
    ),
    (
        frozenset({"create_reply_draft"}),
        "create_reply_draft: the reply goes to the original sender. If the original was sent from this mailbox, "
        "the reply is addressed to the mailbox itself; use create_draft with explicit recipients instead.",
    ),
    (
        frozenset({"delete_draft"}),
        "delete_draft: drafts only; anything else is refused (not_a_draft). Deleted items stay recoverable in "
        "Deleted Items.",
    ),
    (
        frozenset({"get_attachment_text"}),
        "get_attachment_text: reads PDF or plain-text attachments (TXT, CSV, XML, JSON) without downloading "
        "the file; size and page caps apply.",
    ),
    (
        frozenset({"save_attachment_to_storage"}),
        "save_attachment_to_storage: queues the file for asynchronous delivery; key is a relative path. A result "
        'means queued, not delivered. Names ending with "." are refused.',
    ),
    (
        frozenset({"save_attachment_to_path"}),
        "save_attachment_to_path (local only): writes to the server's own disk.",
    ),
)

_SEND_TOOLS = frozenset({"send_email", "send_draft_email"})
_NO_SENDING = (
    "This deployment does not allow sending (no send tools): prepare drafts instead."
)


def build_instructions(registered: Collection[str], append: str = "") -> str:
    """Build the instructions text; a line appears only when one of its tools is registered."""
    names = set(registered)
    lines = [_PURPOSE]
    lines.extend(text for gate, text in _LINES if gate & names)
    reading = [n for n in ("list_inbox", "get_thread") if n in names]
    if reading:
        lines.append(
            f"{' / '.join(reading)}: before deciding a message is unanswered, check the whole thread "
            "(including sent items), not just the inbox view."
            if "get_thread" in names
            else f"{reading[0]}: a message may already be answered in sent items; check before deciding it is unanswered."
        )
    parts = []
    if names & {"move_email", "move_emails", "list_inbox", "create_mail_folder"}:
        parts.append("Folder names resolve case-insensitively (a path such as Parent/Child also works).")
    batch = [n for n in ("move_emails", "set_messages_categories") if n in names]
    if batch:
        parts.append(f"Prefer {' / '.join(batch)} for many messages.")
    if parts:
        lines.append(" ".join(parts))
    if names and not (_SEND_TOOLS & names):
        lines.append(_NO_SENDING)
    text = "\n".join(lines)
    extra = (append or "").strip()[:APPEND_MAX_CHARS]
    if extra:
        text = f"{text}\n{extra}"
    return text
