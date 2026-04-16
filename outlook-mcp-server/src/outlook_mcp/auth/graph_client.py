"""Async HTTP client for Microsoft Graph mail endpoints."""

from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import quote

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _importance_rank(importance: str | None) -> int:
    """Numeric rank for sorting (higher = more important). Unknown or missing → normal."""
    if not importance or not isinstance(importance, str):
        return 2
    v = importance.strip().lower()
    if v == "high":
        return 3
    if v == "low":
        return 1
    return 2


class MailFolderNotFoundError(Exception):
    """No mail folder matched the given display name (case-insensitive)."""

    def __init__(self, display_name: str) -> None:
        self.display_name = display_name
        super().__init__(f"No folder named {display_name!r}")


class MailFolderAmbiguousError(Exception):
    """More than one mail folder matched the display name."""

    def __init__(self, display_name: str, match_count: int) -> None:
        self.display_name = display_name
        self.match_count = match_count
        super().__init__(
            f"Multiple folders ({match_count}) named {display_name!r}; use folder_id from list_folders."
        )


def _encode_message_id_for_path(message_id: str) -> str:
    """Percent-encode a Graph ``message`` id for use in a URL path (``+``, ``/``, ``=``, etc.)."""
    return quote(message_id.strip(), safe="")


def _encode_mail_folder_id_for_path(folder_id: str) -> str:
    """Percent-encode a mail folder id or well-known name for use in a URL path segment."""
    return quote(folder_id.strip(), safe="")


class GraphMailClient:
    """Thin Graph REST wrapper using httpx (supports ``$search`` + ConsistencyLevel header).

    ``mailbox`` unset → delegated ``/me/...``. When set (UPN or user id), paths use
    ``/users/{mailbox}/...`` (application permissions).
    """

    def __init__(
        self,
        access_token: str,
        *,
        http_timeout: float = 30.0,
        mailbox: str | None = None,
    ) -> None:
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        self._http_timeout = http_timeout
        self._mailbox = (mailbox or "").strip() or None

    def _user_prefix(self) -> str:
        if not self._mailbox:
            return "/me"
        enc = quote(self._mailbox, safe="")
        return f"/users/{enc}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=GRAPH_BASE, headers=self._headers, timeout=self._http_timeout)

    async def get_message(self, message_id: str, select: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if select:
            params["$select"] = select
        enc = _encode_message_id_for_path(message_id)
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(f"{base}/messages/{enc}", params=params or None)
            r.raise_for_status()
            return r.json()

    async def list_messages_by_conversation(
        self, conversation_id: str, top: int = 50, *, select: str | None = None
    ) -> dict[str, Any]:
        """Return messages for a thread, sorted by ``receivedDateTime`` ascending (oldest first)."""

        # OData single quotes in filter must be doubled.
        # Do not add $orderby: Graph often returns 400 InefficientFilter for
        # $filter=conversationId combined with $orderby on /me/messages.
        cid = conversation_id.strip()
        safe = cid.replace("'", "''")
        filt = f"conversationId eq '{safe}'"
        params: dict[str, str] = {
            "$filter": filt,
            "$top": str(top),
        }
        if select:
            params["$select"] = select
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(f"{base}/messages", params=params)
            r.raise_for_status()
            body = r.json()
        values = list(body.get("value") or [])
        values.sort(key=lambda m: (m.get("receivedDateTime") or ""))
        body["value"] = values
        return body

    async def search_messages(
        self, query: str, top: int = 25, *, select: str | None = None
    ) -> dict[str, Any]:
        safe_query = query.replace('"', '\\"')
        params: dict[str, str] = {"$search": f'"{safe_query}"', "$top": str(top)}
        if select:
            params["$select"] = select
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(
                f"{base}/messages",
                params=params,
                headers={**self._headers, "ConsistencyLevel": "eventual"},
            )
            r.raise_for_status()
            return r.json()

    async def list_inbox(
        self,
        top: int = 25,
        skip: int = 0,
        *,
        select: str | None = None,
        inbox_filter: str | None = None,
        folder_id: str | None = None,
        sort_by_priority: bool = False,
    ) -> dict[str, Any]:
        """List messages in a mail folder, newest first (default folder: well-known ``inbox``).

        ``folder_id`` is a Graph mail folder id from ``list_folders``, or a well-known name
        such as ``inbox``, ``sentitems``, ``drafts``, ``archive`` (case-insensitive in practice).

        ``inbox_filter`` is the full OData ``$filter`` string (e.g. ``isRead eq false``,
        ``receivedDateTime`` bounds). If Graph returns 400 ``InefficientFilter`` for
        ``$filter`` combined with ``$orderby``, retries without ``$orderby``, sorts in memory
        (by importance then ``receivedDateTime`` when ``sort_by_priority`` is true), then
        applies ``skip`` / ``top``.
        """
        folder_segment = _encode_mail_folder_id_for_path(folder_id) if folder_id else "inbox"
        orderby = (
            "importance desc,receivedDateTime desc"
            if sort_by_priority
            else "receivedDateTime desc"
        )
        params: dict[str, str] = {
            "$top": str(top),
            "$skip": str(skip),
            "$orderby": orderby,
        }
        if inbox_filter:
            params["$filter"] = inbox_filter
        if select:
            params["$select"] = select
        base = self._user_prefix()
        messages_path = f"{base}/mailFolders/{folder_segment}/messages"
        async with self._client() as c:
            r = await c.get(messages_path, params=params)
            if r.status_code == 400 and inbox_filter:
                err = (r.text or "").lower()
                if "inefficientfilter" in err or "inefficient filter" in err:
                    return await self._list_inbox_filter_fallback(
                        c,
                        messages_path,
                        inbox_filter=inbox_filter,
                        top=top,
                        skip=skip,
                        select=select,
                        sort_by_priority=sort_by_priority,
                    )
            r.raise_for_status()
            return r.json()

    async def _list_inbox_filter_fallback(
        self,
        c: httpx.AsyncClient,
        messages_path: str,
        *,
        inbox_filter: str,
        top: int,
        skip: int,
        select: str | None,
        sort_by_priority: bool = False,
    ) -> dict[str, Any]:
        """Folder message list without ``$orderby`` when Graph rejects filter+orderby (sort locally)."""
        # Without server-side ``$orderby``, priority sorting requires a wider sample.
        need = 999 if sort_by_priority else min(skip + top, 999)
        params: dict[str, str] = {
            "$filter": inbox_filter,
            "$top": str(need),
        }
        if select:
            params["$select"] = select
        r = await c.get(messages_path, params=params)
        r.raise_for_status()
        body = r.json()
        values = list(body.get("value") or [])
        if sort_by_priority:
            values.sort(
                key=lambda m: (
                    _importance_rank(m.get("importance")),
                    m.get("receivedDateTime") or "",
                ),
                reverse=True,
            )
        else:
            values.sort(
                key=lambda m: (m.get("receivedDateTime") or ""),
                reverse=True,
            )
        body["value"] = values[skip : skip + top]
        return body

    async def list_attachments(self, message_id: str) -> dict[str, Any]:
        enc = _encode_message_id_for_path(message_id)
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(f"{base}/messages/{enc}/attachments")
            r.raise_for_status()
            return r.json()

    async def list_master_categories(self, top: int = 500) -> dict[str, Any]:
        """Outlook master categories (display name, color); requires ``MailboxSettings.Read``.

        ``top`` is Graph ``$top`` (max rows). Use a large value if you need the full list.
        """
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(f"{base}/outlook/masterCategories", params={"$top": str(top)})
            r.raise_for_status()
            return r.json()

    async def send_mail(self, payload: dict[str, Any]) -> None:
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.post(f"{base}/sendMail", json=payload)
            r.raise_for_status()

    async def create_message_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.post(f"{base}/messages", json=payload)
            r.raise_for_status()
            return r.json()

    async def send_draft(self, message_id: str) -> None:
        """Send an existing draft message by Graph message id."""
        enc = _encode_message_id_for_path(message_id)
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.post(f"{base}/messages/{enc}/send")
            r.raise_for_status()

    async def update_message(self, message_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        enc = _encode_message_id_for_path(message_id)
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.patch(f"{base}/messages/{enc}", json=payload)
            r.raise_for_status()
            if r.content:
                return r.json()
            return {}

    async def move_message(self, message_id: str, destination_id: str) -> dict[str, Any]:
        """Move a message to a different folder. Returns the moved message."""
        enc = _encode_message_id_for_path(message_id)
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.post(f"{base}/messages/{enc}/move", json={"destinationId": destination_id})
            r.raise_for_status()
            return r.json()

    async def create_reply(self, message_id: str, comment: str | None = None) -> dict[str, Any]:
        """Create a reply draft for a message (pre-populated with sender, subject, quoted body).

        Returns the created draft message.
        """
        enc = _encode_message_id_for_path(message_id)
        base = self._user_prefix()
        async with self._client() as c:
            if comment:
                r = await c.post(f"{base}/messages/{enc}/createReply", json={"comment": comment})
            else:
                r = await c.post(f"{base}/messages/{enc}/createReply")
            r.raise_for_status()
            return r.json()

    async def list_folders(self, top: int = 100) -> dict[str, Any]:
        """List mail folders for the signed-in user."""
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(f"{base}/mailFolders", params={"$top": str(top)})
            r.raise_for_status()
            return r.json()

    async def resolve_mail_folder_id_by_display_name(
        self,
        display_name: str,
        *,
        max_folder_requests: int = 400,
    ) -> str:
        """Return the Graph ``id`` for a unique folder whose ``displayName`` matches (case-insensitive).

        Walks the folder tree (root ``mailFolders``, then ``childFolders`` BFS). If no match,
        raises ``MailFolderNotFoundError``. If more than one match, raises ``MailFolderAmbiguousError``.
        """
        needle = (display_name or "").strip()
        if not needle:
            raise ValueError("folder_name must be a non-empty string")
        needle_cf = needle.casefold()

        matches: set[str] = set()

        def consider(folder: dict[str, Any]) -> None:
            dn = (folder.get("displayName") or "").strip()
            if dn.casefold() != needle_cf:
                return
            fid = folder.get("id")
            if isinstance(fid, str) and fid:
                matches.add(fid)
            if len(matches) > 1:
                raise MailFolderAmbiguousError(needle, len(matches))

        base = self._user_prefix()
        requests_made = 0

        async with self._client() as c:
            queue: deque[str] = deque()

            r = await c.get(f"{base}/mailFolders", params={"$top": "999"})
            requests_made += 1
            r.raise_for_status()
            for folder in r.json().get("value") or []:
                consider(folder)
                fid = folder.get("id")
                if isinstance(fid, str) and fid:
                    queue.append(fid)

            while queue and requests_made < max_folder_requests:
                parent_id = queue.popleft()
                enc = _encode_mail_folder_id_for_path(parent_id)
                r2 = await c.get(
                    f"{base}/mailFolders/{enc}/childFolders",
                    params={"$top": "999"},
                )
                requests_made += 1
                r2.raise_for_status()
                for folder in r2.json().get("value") or []:
                    consider(folder)
                    cid = folder.get("id")
                    if isinstance(cid, str) and cid:
                        queue.append(cid)

        if len(matches) > 1:
            raise MailFolderAmbiguousError(needle, len(matches))
        if len(matches) == 0:
            raise MailFolderNotFoundError(needle)
        return next(iter(matches))

    async def create_mail_folder(
        self, display_name: str, *, parent_folder_id: str | None = None
    ) -> dict[str, Any]:
        """Create a top-level mail folder, or a subfolder under ``parent_folder_id``."""
        base = self._user_prefix()
        payload = {"displayName": display_name.strip()}
        async with self._client() as c:
            if parent_folder_id:
                enc = _encode_mail_folder_id_for_path(parent_folder_id)
                r = await c.post(f"{base}/mailFolders/{enc}/childFolders", json=payload)
            else:
                r = await c.post(f"{base}/mailFolders", json=payload)
            r.raise_for_status()
            return r.json()
