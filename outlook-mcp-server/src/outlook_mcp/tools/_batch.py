"""Graph JSON ``$batch`` orchestration: chunking, bounded concurrency, Retry-After-aware retries.

Exchange throttles per mailbox (``MailboxConcurrency``: a handful of concurrent requests per
app + mailbox). Every sub-request of a batch counts, so we keep only a couple of batches in
flight, and retry just the sub-requests that came back 429/503/504.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from outlook_mcp.auth.graph_client import GraphMailClient

GRAPH_BATCH_MAX_REQUESTS = 20
RETRYABLE_STATUSES = frozenset({429, 503, 504})
# 429 guarantees the request was not executed; 503/504 do not (a timed-out move may have happened,
# and re-sending it would 404 on the now-stale id). Non-idempotent callers should pass this set.
THROTTLE_ONLY_STATUSES = frozenset({429})


@dataclass(frozen=True)
class BatchOutcome:
    """Final result of one sub-request (``status`` 0 = never got an HTTP answer)."""

    status: int
    body: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def chunked(items: list[Any], size: int = GRAPH_BATCH_MAX_REQUESTS) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def retry_after_seconds(headers: Any) -> float | None:
    """Parse a ``Retry-After`` header (seconds form) from a dict or httpx ``Headers``; None if absent."""
    if not headers:
        return None
    value = None
    for k, v in dict(headers).items():
        if str(k).lower() == "retry-after":
            value = v
            break
    if value is None:
        return None
    try:
        return max(0.0, float(str(value).strip()))
    except ValueError:
        return None  # HTTP-date form: fall back to exponential backoff


def outcome_error_message(outcome: BatchOutcome) -> str | None:
    """``error.message`` (or code) from a failed sub-response body; None on success."""
    if outcome.ok:
        return None
    body = outcome.body
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code, msg = err.get("code"), err.get("message")
            if code and msg:
                return f"{code}: {msg}"
            return str(msg or code or f"HTTP {outcome.status}")
    return f"HTTP {outcome.status}"


async def run_graph_batch(
    client: GraphMailClient,
    requests: list[dict[str, Any]],
    *,
    max_attempts: int = 5,
    concurrency: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    retry_statuses: frozenset[int] = RETRYABLE_STATUSES,
) -> dict[str, BatchOutcome]:
    """Run sub-requests (each with a unique string ``id``) through ``/$batch``; return outcomes by id.

    Requests are split into chunks of 20; at most ``concurrency`` chunks run at once. Within a
    chunk, sub-requests answered with a ``retry_statuses`` code (default 429/503/504; pass
    ``THROTTLE_ONLY_STATUSES`` for non-idempotent requests) or missing from the response are re-sent after
    the largest ``Retry-After`` seen, or exponential backoff when Graph gives none — up to
    ``max_attempts`` total tries. Never raises for HTTP failures: they become outcomes.
    """
    results: dict[str, BatchOutcome] = {}
    sem = asyncio.Semaphore(max(1, concurrency))

    async def run_chunk(chunk: list[dict[str, Any]]) -> None:
        pending = {str(r["id"]): r for r in chunk}
        for attempt in range(1, max_attempts + 1):
            last = attempt == max_attempts
            wait: float | None = None
            try:
                data = await client.batch(list(pending.values()))
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status not in retry_statuses or last:
                    body = _safe_json(e.response)
                    for rid in pending:
                        results[rid] = BatchOutcome(status, body)
                    return
                wait = retry_after_seconds(e.response.headers)
            except (httpx.HTTPError, ValueError) as e:
                # ValueError: envelope body was not JSON. Retry like a transport failure.
                if last:
                    for rid in pending:
                        results[rid] = BatchOutcome(
                            0, {"error": {"code": "network_error", "message": type(e).__name__}}
                        )
                    return
            else:
                retry: dict[str, dict[str, Any]] = {}
                responses = data.get("responses") if isinstance(data, dict) else None
                for resp in responses if isinstance(responses, list) else []:
                    if not isinstance(resp, dict):
                        continue
                    rid = str(resp.get("id"))
                    if rid not in pending:
                        continue
                    try:
                        status = int(resp.get("status") or 0)
                    except (TypeError, ValueError):
                        status = 0
                    if status in retry_statuses and not last:
                        retry[rid] = pending[rid]
                        ra = retry_after_seconds(resp.get("headers"))
                        if ra is not None:
                            wait = max(wait or 0.0, ra)
                    else:
                        results[rid] = BatchOutcome(status, resp.get("body"))
                for rid, req in pending.items():
                    if rid in results or rid in retry:
                        continue
                    if last:
                        results[rid] = BatchOutcome(
                            0, {"error": {"code": "missing_response", "message": "No sub-response from $batch"}}
                        )
                    else:
                        retry[rid] = req
                pending = retry
                if not pending:
                    return
            backoff = base_delay * (2 ** (attempt - 1))
            # Retry-After: 0 (or missing) must not turn into a zero-delay retry storm.
            delay = max(wait, base_delay) if wait is not None else backoff
            await sleep(min(delay, max_delay))

    async def guarded(chunk: list[dict[str, Any]]) -> None:
        async with sem:
            await run_chunk(chunk)

    await asyncio.gather(*(guarded(c) for c in chunked(requests)))
    return results


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"error": {"code": f"HTTP{response.status_code}", "message": (response.text or "")[:500]}}
