"""Minimal Azure Blob Storage writer over plain HTTPS (no Azure SDK).

Authenticates with a bearer token (e.g. from a managed identity). Nothing here logs; error
messages never contain tokens, keys, file names or content.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, urlsplit

import httpx

MAX_KEY_LENGTH = 1024
BLOB_API_VERSION = "2023-11-03"
STORAGE_RESOURCE = "https://storage.azure.com/"
_BLOB_HOST_SUFFIX = ".blob.core.windows.net"
_CONTAINER_NAME_RE = re.compile(r"^[a-z0-9](?!.*--)[a-z0-9-]{1,61}[a-z0-9]$")
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


class StorageConfigError(ValueError):
    """The storage configuration (container URL) is invalid."""


def normalize_container_url(container_url: str) -> str:
    """Return ``https://<acct>.blob.core.windows.net/<container>`` or raise ``StorageConfigError``."""
    raw = (container_url or "").strip()
    err = StorageConfigError(
        "ATTACHMENT_BLOB_CONTAINER_URL must look like https://<account>.blob.core.windows.net/<container>."
    )
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise err from None
    segments = [p for p in parts.path.split("/") if p]
    ok = (
        parts.scheme == "https"
        and host.endswith(_BLOB_HOST_SUFFIX)
        and len(host) > len(_BLOB_HOST_SUFFIX)
        and port is None
        and not parts.username
        and not parts.query
        and not parts.fragment
        and len(segments) == 1
        and parts.path.rstrip("/") == "/" + segments[0]
        and (segments[0] == "$root" or _CONTAINER_NAME_RE.match(segments[0]) is not None)
    )
    if not ok:
        raise err
    return f"https://{host}/{segments[0]}"


def _validate_shape(key: str) -> str:
    """Shared key rules (no prefix check); returns the NFC-normalized key or raises ``ValueError(code)``."""
    if key is None or not key.strip():
        raise ValueError("empty")
    k = unicodedata.normalize("NFC", key)
    if len(k) > MAX_KEY_LENGTH:
        raise ValueError("too_long")
    if k.startswith("/"):
        raise ValueError("absolute")
    if "\\" in k:
        raise ValueError("backslash")
    if any(unicodedata.category(c) in _FORBIDDEN_CATEGORIES for c in k):
        raise ValueError("control_char")
    segments = k.split("/")
    if any(s in ("..", ".") for s in segments):
        raise ValueError("dotdot")
    if any(s == "" for s in segments):
        raise ValueError("empty_segment")
    # Compatibility look-alikes (full-width dots/slashes, two-dot leader, ...) must not change the structure.
    nk = unicodedata.normalize("NFKC", k)
    nsegs = nk.split("/")
    if "\\" in nk or nk.count("/") != k.count("/") or any(s in ("..", ".", "") for s in nsegs):
        raise ValueError("dotdot" if any(s in ("..", ".") for s in nsegs) else "confusable")
    if any(s != s.strip() or s.endswith(".") for s in segments):
        raise ValueError("bad_segment_edge")
    return k


def parse_allowed_prefixes(value: str) -> list[str]:
    """Parse and validate the configured prefixes; invalid ones are a configuration error."""
    out: list[str] = []
    for raw in (value or "").split(","):
        if not raw.strip():
            continue
        try:
            out.append(_validate_shape(raw.strip().rstrip("/") or "/").rstrip("/"))
        except ValueError as e:
            raise StorageConfigError(f"ATTACHMENT_ALLOWED_PREFIXES contains an invalid prefix ({e}).") from None
    return out


def validate_storage_key(key: str, allowed_prefixes: list[str]) -> str:
    """Return the NFC-normalized key, or raise ``ValueError`` whose message is a reason code."""
    k = _validate_shape(key)
    prefixes = [unicodedata.normalize("NFC", p).rstrip("/") for p in allowed_prefixes if p.strip("/")]
    if prefixes and not any(k == p or k.startswith(p + "/") for p in prefixes):
        raise ValueError("prefix_not_allowed")
    return k


def put_blob(
    container_url: str,
    key: str,
    data: bytes,
    content_type: str,
    token: str,
    http: httpx.Client,
) -> None:
    """``PUT`` a block blob. Raises ``httpx.HTTPStatusError`` / ``httpx.HTTPError`` on failure."""
    base = normalize_container_url(container_url)
    url = base + "/" + "/".join(quote(seg, safe="") for seg in key.split("/"))
    ctype = content_type if content_type.isascii() and content_type.isprintable() else "application/octet-stream"
    resp = http.put(
        url,
        content=data,
        headers={
            "x-ms-blob-type": "BlockBlob",
            "x-ms-version": BLOB_API_VERSION,
            "x-ms-blob-content-type": ctype or "application/octet-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    resp.raise_for_status()
