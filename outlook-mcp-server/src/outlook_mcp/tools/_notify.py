"""MCP client notifications: logging and progress (no-op when ``ctx`` is None)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Awaitable

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)

# Bound notify work so tools never block on slow/disabled inspector transports.
_NOTIFY_TIMEOUT_S = 0.2


def _preview(text: str, max_len: int = 8) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


async def _safe_notify(awaitable: Awaitable[Any]) -> None:
    """Run MCP notify coroutine with timeout; swallow errors (best-effort only)."""
    try:
        await asyncio.wait_for(awaitable, timeout=_NOTIFY_TIMEOUT_S)
    except TimeoutError:
        logger.debug("MCP notify timed out after %.2fs", _NOTIFY_TIMEOUT_S)
    except Exception:
        logger.debug("MCP notify failed", exc_info=True)


async def tool_log_info(ctx: Context | None, message: str, *, logger_name: str = "outlook_mcp") -> None:
    if ctx is None:
        return
    await _safe_notify(ctx.log("info", message, logger_name=logger_name))


async def tool_log_warning(ctx: Context | None, message: str, *, logger_name: str = "outlook_mcp") -> None:
    if ctx is None:
        return
    await _safe_notify(ctx.log("warning", message, logger_name=logger_name))


async def tool_log_error(ctx: Context | None, message: str, *, logger_name: str = "outlook_mcp") -> None:
    if ctx is None:
        return
    await _safe_notify(ctx.log("error", message, logger_name=logger_name))


async def tool_report_progress(
    ctx: Context | None,
    progress: float,
    total: float = 100.0,
    message: str | None = None,
) -> None:
    if ctx is None:
        return
    await _safe_notify(ctx.report_progress(progress, total=total, message=message))


__all__ = ["tool_log_error", "tool_log_info", "tool_log_warning", "tool_report_progress"]
