"""Attachment input validation/decoding helpers and Graph payload builders."""

from __future__ import annotations

import base64

import pytest

from outlook_mcp.tools._attachments import (
    SMALL_ATTACHMENT_THRESHOLD_BYTES,
    AttachmentInput,
    attach_files_to_message,
    build_inline_small_attachments_payload,
    decode_attachment_base64,
    guess_content_type,
    has_large_attachment,
    minimal_attachment_result,
    parse_attachment_inputs,
    read_attachment_file_bytes,
    resolve_attachment_bytes,
    validate_attachment_limits,
)


def test_parse_attachment_inputs_valid() -> None:
    raw = [{"filename": "a.txt", "content_base64": "aGVsbG8="}]
    parsed = parse_attachment_inputs(raw)
    assert len(parsed) == 1
    assert isinstance(parsed[0], AttachmentInput)
    assert parsed[0].filename == "a.txt"
    assert parsed[0].content_base64 == "aGVsbG8="
    assert parsed[0].is_inline is False


def test_parse_attachment_inputs_none_returns_empty_list() -> None:
    assert parse_attachment_inputs(None) == []


def test_parse_attachment_inputs_missing_filename_raises() -> None:
    with pytest.raises(ValueError):
        parse_attachment_inputs([{"content_base64": "aGVsbG8="}])


def test_parse_attachment_inputs_missing_content_base64_raises() -> None:
    with pytest.raises(ValueError):
        parse_attachment_inputs([{"filename": "a.txt"}])


def test_decode_attachment_base64_valid() -> None:
    assert decode_attachment_base64("aGVsbG8=") == b"hello"


def test_decode_attachment_base64_invalid_raises() -> None:
    with pytest.raises(ValueError):
        decode_attachment_base64("not-valid-base64!!")


def test_guess_content_type_uses_declared_value() -> None:
    assert guess_content_type("a.txt", "application/custom") == "application/custom"


def test_guess_content_type_falls_back_to_extension() -> None:
    assert guess_content_type("photo.png", None) == "image/png"


def test_guess_content_type_falls_back_to_octet_stream_for_unknown_extension() -> None:
    assert guess_content_type("mystery.unknownext", None) == "application/octet-stream"


def test_build_inline_small_attachments_payload_shape() -> None:
    attachments = [
        AttachmentInput(filename="a.txt", content_type="text/plain", content_base64="aGVsbG8=", is_inline=False),
    ]
    payload = build_inline_small_attachments_payload(attachments)
    assert payload == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "a.txt",
            "contentType": "text/plain",
            "contentBytes": "aGVsbG8=",
            "isInline": False,
        }
    ]


def test_build_inline_small_attachments_payload_guesses_content_type() -> None:
    attachments = [AttachmentInput(filename="a.png", content_base64="aGVsbG8=")]
    payload = build_inline_small_attachments_payload(attachments)
    assert payload[0]["contentType"] == "image/png"


def test_validate_attachment_limits_ok() -> None:
    attachments = [AttachmentInput(filename="a.txt", content_base64="aGVsbG8=")]
    validate_attachment_limits(attachments, max_count=10, max_bytes=1024)  # should not raise


def test_validate_attachment_limits_too_many_raises() -> None:
    attachments = [AttachmentInput(filename=f"{i}.txt", content_base64="aGVsbG8=") for i in range(3)]
    with pytest.raises(ValueError):
        validate_attachment_limits(attachments, max_count=2, max_bytes=1024)


def test_validate_attachment_limits_oversized_raises() -> None:
    attachments = [AttachmentInput(filename="a.txt", content_base64="aGVsbG8=")]
    with pytest.raises(ValueError):
        validate_attachment_limits(attachments, max_count=10, max_bytes=1)


def test_validate_attachment_limits_empty_file_raises() -> None:
    with pytest.raises(ValueError):
        parse_attachment_inputs([{"filename": "empty.txt", "content_base64": ""}])


def test_validate_attachment_limits_empty_file_path_raises(tmp_path) -> None:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    attachments = [AttachmentInput(file_path=str(f))]
    with pytest.raises(ValueError):
        validate_attachment_limits(attachments, max_count=10, max_bytes=1024)


def test_validate_attachment_limits_bad_base64_raises() -> None:
    attachments = [AttachmentInput(filename="a.txt", content_base64="not-valid-base64!!")]
    with pytest.raises(ValueError):
        validate_attachment_limits(attachments, max_count=10, max_bytes=1024)


def test_attachment_input_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError):
        AttachmentInput(filename="a.txt")


def test_attachment_input_rejects_both_sources() -> None:
    with pytest.raises(ValueError):
        AttachmentInput(filename="a.txt", content_base64="aGVsbG8=", file_path="/tmp/a.txt")


def test_attachment_input_filename_defaults_to_basename_from_file_path(tmp_path) -> None:
    f = tmp_path / "invoice.pdf"
    f.write_bytes(b"%PDF-1.4")
    a = AttachmentInput(file_path=str(f))
    assert a.filename == "invoice.pdf"


def test_attachment_input_filename_required_when_using_content_base64() -> None:
    with pytest.raises(ValueError):
        AttachmentInput(content_base64="aGVsbG8=")


def test_read_attachment_file_bytes_reads_file(tmp_path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert read_attachment_file_bytes(str(f)) == b"hello"


def test_read_attachment_file_bytes_missing_file_raises(tmp_path) -> None:
    with pytest.raises(ValueError):
        read_attachment_file_bytes(str(tmp_path / "does-not-exist.txt"))


def test_resolve_attachment_bytes_from_content_base64() -> None:
    a = AttachmentInput(filename="a.txt", content_base64="aGVsbG8=")
    assert resolve_attachment_bytes(a) == b"hello"


def test_resolve_attachment_bytes_from_file_path(tmp_path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello from disk")
    a = AttachmentInput(file_path=str(f))
    assert resolve_attachment_bytes(a) == b"hello from disk"


def test_build_inline_small_attachments_payload_from_file_path(tmp_path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    attachments = [AttachmentInput(file_path=str(f), content_type="text/plain")]
    payload = build_inline_small_attachments_payload(attachments)
    assert payload == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "a.txt",
            "contentType": "text/plain",
            "contentBytes": "aGVsbG8=",
            "isInline": False,
        }
    ]


def test_validate_attachment_limits_oversized_file_path_raises(tmp_path) -> None:
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 10)
    attachments = [AttachmentInput(file_path=str(f))]
    with pytest.raises(ValueError):
        validate_attachment_limits(attachments, max_count=10, max_bytes=1)


def test_has_large_attachment_true_for_large_file_path(tmp_path) -> None:
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * (SMALL_ATTACHMENT_THRESHOLD_BYTES + 1))
    attachments = [AttachmentInput(file_path=str(f))]
    assert has_large_attachment(attachments) is True


@pytest.mark.asyncio
async def test_attach_files_to_message_routes_file_path_small_file(tmp_path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")

    class FakeClient:
        async def add_attachment_small(self, message_id, *, name, content_type, content_b64, is_inline=False):
            return {"id": "att-1", "name": name, "size": len(base64.b64decode(content_b64)), "contentType": content_type}

        async def upload_large_attachment(self, *args, **kwargs):
            raise AssertionError("should not be called for a small file")

    attachments = [AttachmentInput(file_path=str(f), content_type="text/plain")]
    results = await attach_files_to_message(FakeClient(), "msg-1", attachments)
    assert results == [{"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}]


def test_has_large_attachment_false_for_small_only() -> None:
    attachments = [AttachmentInput(filename="a.txt", content_base64="aGVsbG8=")]
    assert has_large_attachment(attachments) is False


def test_has_large_attachment_true_when_one_exceeds_threshold() -> None:
    big_b64 = base64.b64encode(b"x" * (SMALL_ATTACHMENT_THRESHOLD_BYTES + 1)).decode()
    attachments = [
        AttachmentInput(filename="a.txt", content_base64="aGVsbG8="),
        AttachmentInput(filename="big.bin", content_base64=big_b64),
    ]
    assert has_large_attachment(attachments) is True


def test_minimal_attachment_result_strips_content_bytes() -> None:
    graph_response = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": "att-1",
        "name": "invoice.pdf",
        "contentType": "application/pdf",
        "size": 95000,
        "isInline": False,
        "lastModifiedDateTime": "2026-01-01T00:00:00Z",
        "contentBytes": "A" * 95000,
    }
    assert minimal_attachment_result(graph_response) == {
        "id": "att-1",
        "name": "invoice.pdf",
        "size": 95000,
        "contentType": "application/pdf",
    }


@pytest.mark.asyncio
async def test_attach_files_to_message_strips_content_bytes_from_result() -> None:
    class FakeClient:
        async def add_attachment_small(self, message_id, *, name, content_type, content_b64, is_inline=False):
            return {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "att-1",
                "name": name,
                "contentType": content_type,
                "size": len(base64.b64decode(content_b64)),
                "isInline": is_inline,
                "lastModifiedDateTime": "2026-01-01T00:00:00Z",
                "contentBytes": content_b64,
            }

        async def upload_large_attachment(self, *args, **kwargs):
            raise AssertionError("should not be called for a small file")

    attachments = [AttachmentInput(filename="a.txt", content_type="text/plain", content_base64="aGVsbG8=")]
    results = await attach_files_to_message(FakeClient(), "msg-1", attachments)
    assert results == [{"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}]
    assert "contentBytes" not in results[0]


@pytest.mark.asyncio
async def test_attach_files_to_message_routes_small_file_to_add_attachment_small() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.small_calls: list[dict] = []
            self.large_calls: list[dict] = []

        async def add_attachment_small(self, message_id, *, name, content_type, content_b64, is_inline=False):
            self.small_calls.append(
                {"message_id": message_id, "name": name, "content_type": content_type, "is_inline": is_inline}
            )
            return {"id": "att-1", "name": name, "size": len(base64.b64decode(content_b64)), "contentType": content_type}

        async def upload_large_attachment(self, *args, **kwargs):
            self.large_calls.append(kwargs)
            raise AssertionError("should not be called for a small file")

    client = FakeClient()
    attachments = [AttachmentInput(filename="a.txt", content_type="text/plain", content_base64="aGVsbG8=")]
    results = await attach_files_to_message(client, "msg-1", attachments)
    assert results == [{"id": "att-1", "name": "a.txt", "size": 5, "contentType": "text/plain"}]
    assert client.small_calls == [
        {"message_id": "msg-1", "name": "a.txt", "content_type": "text/plain", "is_inline": False}
    ]
    assert client.large_calls == []


@pytest.mark.asyncio
async def test_attach_files_to_message_routes_large_file_to_upload_large_attachment() -> None:
    big_b64 = base64.b64encode(b"x" * (SMALL_ATTACHMENT_THRESHOLD_BYTES + 1)).decode()

    class FakeClient:
        def __init__(self) -> None:
            self.large_calls: list[dict] = []

        async def add_attachment_small(self, *args, **kwargs):
            raise AssertionError("should not be called for a large file")

        async def upload_large_attachment(self, message_id, *, name, content_type, content_bytes, is_inline=False):
            self.large_calls.append({"message_id": message_id, "name": name, "content_type": content_type})
            return {"id": "att-2", "name": name, "size": len(content_bytes), "contentType": content_type}

    client = FakeClient()
    attachments = [AttachmentInput(filename="big.bin", content_type="application/octet-stream", content_base64=big_b64)]
    results = await attach_files_to_message(client, "msg-1", attachments)
    assert results == [
        {
            "id": "att-2",
            "name": "big.bin",
            "size": SMALL_ATTACHMENT_THRESHOLD_BYTES + 1,
            "contentType": "application/octet-stream",
        }
    ]
    assert client.large_calls == [
        {"message_id": "msg-1", "name": "big.bin", "content_type": "application/octet-stream"}
    ]
