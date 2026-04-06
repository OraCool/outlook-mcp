"""Async HTTP client for Microsoft Graph mail endpoints."""

from __future__ import annotations

from typing import Any

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphMailClient:
    """Thin Graph REST wrapper using httpx (supports ``$search`` + ConsistencyLevel header)."""

    def __init__(self, access_token: str, *, http_timeout: float = 30.0) -> None:
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        self._http_timeout = http_timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=GRAPH_BASE, headers=self._headers, timeout=self._http_timeout)

    async def get_message(self, message_id: str, select: str | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if select:
            params["$select"] = select
        async with self._client() as c:
            r = await c.get(f"/me/messages/{message_id}", params=params or None)
            r.raise_for_status()
            return r.json()

    async def list_messages_by_conversation(self, conversation_id: str, top: int = 50) -> dict[str, Any]:
        # OData single quotes in filter must be doubled
        safe = conversation_id.replace("'", "''")
        filt = f"conversationId eq '{safe}'"
        async with self._client() as c:
            r = await c.get(
                "/me/messages",
                params={"$filter": filt, "$top": str(top), "$orderby": "receivedDateTime asc"},
            )
            r.raise_for_status()
            return r.json()

    async def search_messages(self, query: str, top: int = 25) -> dict[str, Any]:
        safe_query = query.replace('"', '\\"')
        async with self._client() as c:
            r = await c.get(
                "/me/messages",
                params={"$search": f'"{safe_query}"', "$top": str(top)},
                headers={**self._headers, "ConsistencyLevel": "eventual"},
            )
            r.raise_for_status()
            return r.json()

    async def list_inbox(self, top: int = 25, skip: int = 0) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get(
                "/me/mailFolders/Inbox/messages",
                params={
                    "$top": str(top),
                    "$skip": str(skip),
                    "$orderby": "receivedDateTime desc",
                },
            )
            r.raise_for_status()
            return r.json()

    async def list_attachments(self, message_id: str) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.get(f"/me/messages/{message_id}/attachments")
            r.raise_for_status()
            return r.json()

    async def list_master_categories(self, top: int = 500) -> dict[str, Any]:
        """Outlook master categories (display name, color); requires ``MailboxSettings.Read``.

        ``top`` is Graph ``$top`` (max rows). Use a large value if you need the full list.
        """
        async with self._client() as c:
            r = await c.get("/me/outlook/masterCategories", params={"$top": str(top)})
            r.raise_for_status()
            return r.json()

    async def send_mail(self, payload: dict[str, Any]) -> None:
        async with self._client() as c:
            r = await c.post("/me/sendMail", json=payload)
            r.raise_for_status()

    async def create_message_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._client() as c:
            r = await c.post("/me/messages", json=payload)
            r.raise_for_status()
            return r.json()
