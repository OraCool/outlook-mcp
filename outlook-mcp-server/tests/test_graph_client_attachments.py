"""GraphMailClient attachment upload/download methods (low-level httpx wrapper)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outlook_mcp.auth.graph_client import GraphMailClient


def _fake_http(**responses: MagicMock) -> MagicMock:
    """A MagicMock standing in for the ``httpx.AsyncClient`` used inside ``async with``."""
    http = MagicMock()
    for method, response in responses.items():
        setattr(http, method, AsyncMock(return_value=response))
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    return http


def _response(*, json_body=None, content=b"", headers=None, status_code=200) -> MagicMock:
    r = MagicMock(status_code=status_code, content=content, headers=headers or {})
    r.json = MagicMock(return_value=json_body if json_body is not None else {})
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.asyncio
async def test_add_attachment_small_posts_correct_payload() -> None:
    posted = _response(json_body={"id": "att-1", "name": "a.txt"})
    http = _fake_http(post=posted)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        result = await client.add_attachment_small(
            "msg-1", name="a.txt", content_type="text/plain", content_b64="aGVsbG8=", is_inline=True
        )
    assert result == {"id": "att-1", "name": "a.txt"}
    url, kwargs = http.post.await_args.args, http.post.await_args.kwargs
    assert url == ("/me/messages/msg-1/attachments",)
    assert kwargs["json"] == {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": "a.txt",
        "contentType": "text/plain",
        "contentBytes": "aGVsbG8=",
        "isInline": True,
    }


@pytest.mark.asyncio
async def test_create_upload_session_returns_session_json() -> None:
    posted = _response(json_body={"uploadUrl": "https://upload.example/session", "expirationDateTime": "later"})
    http = _fake_http(post=posted)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        result = await client.create_upload_session("msg-1", name="big.bin", content_type="application/octet-stream", size=1000)
    assert result == {"uploadUrl": "https://upload.example/session", "expirationDateTime": "later"}
    url = http.post.await_args.args[0]
    assert url == "/me/messages/msg-1/attachments/createUploadSession"


@pytest.mark.asyncio
async def test_upload_session_chunk_sends_content_range_header() -> None:
    put_response = _response(status_code=202, content=b"")
    http = _fake_http(put=put_response)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_raw_client", return_value=http):
        result = await client.upload_session_chunk(
            "https://upload.example/session", chunk=b"abcdef", start=0, total_size=20
        )
    assert result is put_response
    args, kwargs = http.put.await_args.args, http.put.await_args.kwargs
    assert args == ("https://upload.example/session",)
    assert kwargs["content"] == b"abcdef"
    assert kwargs["headers"]["Content-Range"] == "bytes 0-5/20"
    assert kwargs["headers"]["Content-Length"] == "6"


@pytest.mark.asyncio
async def test_upload_large_attachment_orchestrates_chunks_and_returns_final_attachment() -> None:
    content_bytes = b"x" * 10
    session_response = _response(json_body={"uploadUrl": "https://upload.example/session"})
    chunk1 = _response(status_code=202, content=b"")
    chunk2 = _response(status_code=201, content=b"{}", json_body={"id": "att-final", "name": "big.bin", "size": 10})

    http = MagicMock()
    http.put = AsyncMock(side_effect=[chunk1, chunk2])
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)

    client = GraphMailClient("tok")
    with (
        patch.object(GraphMailClient, "_client", return_value=_fake_http(post=session_response)),
        patch.object(GraphMailClient, "_raw_client", return_value=http),
    ):
        result = await client.upload_large_attachment(
            "msg-1", name="big.bin", content_type="application/octet-stream", content_bytes=content_bytes, chunk_size=6
        )

    assert result == {"id": "att-final", "name": "big.bin", "size": 10}
    assert http.put.await_count == 2
    first_headers = http.put.await_args_list[0].kwargs["headers"]
    second_headers = http.put.await_args_list[1].kwargs["headers"]
    assert first_headers["Content-Range"] == "bytes 0-5/10"
    assert second_headers["Content-Range"] == "bytes 6-9/10"


@pytest.mark.asyncio
async def test_get_attachment_returns_metadata() -> None:
    got = _response(json_body={"id": "att-1", "name": "a.txt", "contentType": "text/plain", "size": 5})
    http = _fake_http(get=got)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        result = await client.get_attachment("msg-1", "att-1")
    assert result == {"id": "att-1", "name": "a.txt", "contentType": "text/plain", "size": 5}
    assert http.get.await_args.args == ("/me/messages/msg-1/attachments/att-1",)


@pytest.mark.asyncio
async def test_get_attachment_raw_bytes_returns_bytes_and_content_type() -> None:
    got = _response(content=b"\x89PNG...", headers={"content-type": "image/png"})
    http = _fake_http(get=got)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        content, content_type = await client.get_attachment_raw_bytes("msg-1", "att-1")
    assert content == b"\x89PNG..."
    assert content_type == "image/png"
    assert http.get.await_args.args == ("/me/messages/msg-1/attachments/att-1/$value",)


@pytest.mark.asyncio
async def test_list_attachments_passes_select_param() -> None:
    got = _response(json_body={"value": [{"id": "att-1", "name": "a.txt"}]})
    http = _fake_http(get=got)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        await client.list_attachments("msg-1", select="id,name,contentType,size")
    args, kwargs = http.get.await_args.args, http.get.await_args.kwargs
    assert args == ("/me/messages/msg-1/attachments",)
    assert kwargs["params"] == {"$select": "id,name,contentType,size"}


@pytest.mark.asyncio
async def test_list_attachments_without_select_omits_param() -> None:
    got = _response(json_body={"value": []})
    http = _fake_http(get=got)
    client = GraphMailClient("tok")
    with patch.object(GraphMailClient, "_client", return_value=http):
        await client.list_attachments("msg-1")
    kwargs = http.get.await_args.kwargs
    assert kwargs.get("params") is None
