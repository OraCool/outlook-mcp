"""Tool observability: server-side logs, best-effort client notifications, and progress.

Log entries go to two sinks. The Python logger (stderr) is the source of truth and
always fires. The MCP ``notifications/message`` channel is best-effort: SEP-2577
deprecated the logging capability as of 2026-07-28, and on that protocol delivery is
per-request opt-in, so clients see an entry only when they asked for that level.
Older clients still get everything, which is why the deprecated call is kept.

Progress (``report_progress``) is *not* deprecated and remains a plain client call.
"""

from __future__ import annotations

import asyncio
import logging
import warnings
from typing import TYPE_CHECKING, Any, Awaitable

from mcp import MCPDeprecationWarning

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

from outlook_mcp.tools._common import sanitize_client_error_message

logger = logging.getLogger(__name__)

# Silence only the logging-capability notice, once, at import. A narrow module-level
# filter is used instead of ``warnings.catch_warnings()`` around the call: that context
# manager mutates global state and is not async-safe, so wrapping an ``await`` would
# suppress warnings for unrelated tasks that run while this coroutine is suspended.
# Scoping by message keeps the sampling and roots deprecations visible.
warnings.filterwarnings(
    "ignore",
    message=r"The logging capability is deprecated.*",
    category=MCPDeprecationWarning,
)

# Bound notify work so tools never block on slow/disabled inspector transports.
_NOTIFY_TIMEOUT_S = 0.2

_PY_LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


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


async def _emit(ctx: Context | None, level: str, message: str, logger_name: str) -> None:
    """Log to stderr (always), then mirror to the client (best-effort, deprecated channel)."""
    message = sanitize_client_error_message(message, max_len=800)
    logger.log(_PY_LEVELS[level], message)
    if ctx is None:
        return
    await _safe_notify(ctx.log(level, message, logger_name=logger_name))


async def tool_log_info(ctx: Context | None, message: str, *, logger_name: str = "outlook_mcp") -> None:
    await _emit(ctx, "info", message, logger_name)


async def tool_log_warning(ctx: Context | None, message: str, *, logger_name: str = "outlook_mcp") -> None:
    await _emit(ctx, "warning", message, logger_name)


async def tool_log_error(ctx: Context | None, message: str, *, logger_name: str = "outlook_mcp") -> None:
    await _emit(ctx, "error", message, logger_name)


async def tool_report_progress(
    ctx: Context | None,
    progress: float,
    total: float = 100.0,
    message: str | None = None,
) -> None:
    if ctx is None:
        return
    if message is not None:
        message = sanitize_client_error_message(message, max_len=800)
    await _safe_notify(ctx.report_progress(progress, total=total, message=message))


__all__ = ["tool_log_error", "tool_log_info", "tool_log_warning", "tool_report_progress"]
