"""Dev MCP client stub sampling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.types import CreateMessageRequestParams, SamplingMessage, TextContent

from outlook_mcp.client import stub_sampling_callback


@pytest.mark.asyncio
async def test_stub_sampling_classification_shape() -> None:
    params = CreateMessageRequestParams(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        "AR Email Classification Specialist\n"
                        'Email payload (JSON):\n{"id": "mid-1", "subject": "Hi"}\n'
                        "Return only the classification JSON"
                    ),
                ),
            )
        ],
        maxTokens=100,
    )
    result = await stub_sampling_callback(MagicMock(), params)
    assert result.model == "stub"
    data = json.loads(result.content.text)
    assert data["email_id"] == "mid-1"
    assert data["category"] == "UNCLASSIFIED"
    assert data["confidence"] == 0.0
    assert "intent" in data


@pytest.mark.asyncio
async def test_stub_sampling_extraction_shape() -> None:
    params = CreateMessageRequestParams(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        "Extract structured AR-relevant facts from the email.\n"
                        'Email JSON:\n{"id": "mid-2", "subject": "Inv"}\n'
                    ),
                ),
            )
        ],
        maxTokens=50,
    )
    result = await stub_sampling_callback(MagicMock(), params)
    data = json.loads(result.content.text)
    assert data["email_id"] == "mid-2"
    assert data["invoice_numbers"] == []
    assert "raw_notes" in data
