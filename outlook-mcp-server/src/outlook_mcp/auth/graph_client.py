"""Async HTTP client for Microsoft Graph mail endpoints."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _encode_message_id_for_path(message_id: str) -> str:
    """Percent-encode a Graph ``message`` id for use in a URL path (``+``, ``/``, ``=``, etc.)."""
    return quote(message_id.strip(), safe="")


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
        self, top: int = 25, skip: int = 0, *, select: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "$top": str(top),
            "$skip": str(skip),
            "$orderby": "receivedDateTime desc",
        }
        if select:
            params["$select"] = select
        base = self._user_prefix()
        async with self._client() as c:
            r = await c.get(f"{base}/mailFolders/Inbox/messages", params=params)
            r.raise_for_status()
            return r.json()

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
