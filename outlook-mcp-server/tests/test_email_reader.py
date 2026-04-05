"""Graph client and message mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.auth.graph_client import GraphMailClient
from outlook_mcp.tools._common import graph_message_to_model


def test_graph_message_to_model_minimal() -> None:
    raw = {
        "id": "msg-1",
        "subject": "Hello",
        "bodyPreview": "Hi",
        "body": {"contentType": "text", "content": "Hi there"},
        "from": {"emailAddress": {"address": "a@b.com", "name": "A"}},
        "toRecipients": [{"emailAddress": {"address": "c@d.com"}}],
    }
    m = graph_message_to_model(raw)
    assert m.id == "msg-1"
    assert m.subject == "Hello"
    assert m.from_ is not None
    assert m.from_.address == "a@b.com"


@pytest.mark.asyncio
@patch("outlook_mcp.auth.graph_client.httpx.AsyncClient")
async def test_graph_mail_client_get_message(mock_async_client_class: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "id": "mid",
            "subject": "S",
            "body": {},
        }
    )

    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_response)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    mock_async_client_class.return_value = mock_instance

    gc = GraphMailClient("fake-token")
    out = await gc.get_message("mid", select="id,subject")
    assert out["id"] == "mid"
    mock_instance.get.assert_awaited()
