"""Tests for MCP tool notification helpers."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from outlook_mcp.tools._notify import (
    _preview,
    tool_log_info,
    tool_log_warning,
    tool_report_progress,
)


def test_preview_short() -> None:
    assert _preview("abc") == "abc"


def test_preview_truncates() -> None:
    assert _preview("abcdefghij", max_len=4) == "abcd…"


@pytest.mark.asyncio
async def test_tool_log_info_skips_when_ctx_none() -> None:
    await tool_log_info(None, "x")  # no error


@pytest.mark.asyncio
async def test_tool_log_info_calls_ctx_log() -> None:
    ctx = MagicMock()
    ctx.log = AsyncMock()
    await tool_log_info(ctx, "hello", logger_name="test_logger")
    ctx.log.assert_awaited_once_with("info", "hello", logger_name="test_logger")


@pytest.mark.asyncio
async def test_tool_report_progress_calls_ctx() -> None:
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()
    await tool_report_progress(ctx, 50.0, 100.0, message="half")
    ctx.report_progress.assert_awaited_once_with(50.0, total=100.0, message="half")


@pytest.mark.asyncio
async def test_tool_log_warning() -> None:
    ctx = MagicMock()
    ctx.log = AsyncMock()
    await tool_log_warning(ctx, "warn")
    ctx.log.assert_awaited_once_with("warning", "warn", logger_name="outlook_mcp")


@pytest.mark.asyncio
async def test_tool_log_info_swallows_log_exception() -> None:
    ctx = MagicMock()
    ctx.log = AsyncMock(side_effect=RuntimeError("notify failed"))
    await tool_log_info(ctx, "x")


@pytest.mark.asyncio
async def test_tool_log_info_times_out_slow_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("outlook_mcp.tools._notify._NOTIFY_TIMEOUT_S", 0.05)

    async def slow_log(*_a: object, **_k: object) -> None:
        await asyncio.sleep(1.0)

    ctx = MagicMock()
    ctx.log = AsyncMock(side_effect=slow_log)
    t0 = time.monotonic()
    await tool_log_info(ctx, "x")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.3


@pytest.mark.asyncio
async def test_tool_report_progress_swallows_exception() -> None:
    ctx = MagicMock()
    ctx.report_progress = AsyncMock(side_effect=ValueError("no progress token"))
    await tool_report_progress(ctx, 1.0, 100.0, message="x")
