"""mail_query_params builders."""

import pytest

from outlook_mcp.tools.mail_query_params import (
    build_inbox_odata_filter,
    build_received_datetime_odata_filter,
    build_search_kql_query,
)


def test_inbox_filter_priority_high() -> None:
    f = build_inbox_odata_filter(
        False,
        None,
        None,
        None,
        priority_filter="high",
    )
    assert f == "importance eq 'high'"


def test_inbox_filter_unread_and_day() -> None:
    f = build_inbox_odata_filter(
        True,
        "2024-06-15",
        None,
        None,
    )
    assert f is not None
    assert "isRead eq false" in f
    assert "receivedDateTime ge 2024-06-15T00:00:00.0000000Z" in f
    assert "receivedDateTime lt 2024-06-16T00:00:00.0000000Z" in f


def test_inbox_filter_received_range_datetimes() -> None:
    f = build_inbox_odata_filter(
        False,
        None,
        "2024-01-01",
        "2024-12-31T00:00:00Z",
    )
    assert "receivedDateTime ge 2024-01-01T00:00:00.0000000Z" in f
    assert "receivedDateTime lt 2024-12-31T00:00:00.0000000Z" in f


def test_conflicting_received_params_raises() -> None:
    with pytest.raises(ValueError, match="received_on"):
        build_received_datetime_odata_filter("2024-01-01", "2024-02-01", None)


def test_search_kql_read_and_dates() -> None:
    q = build_search_kql_query(
        "subject:pay",
        read_filter="unread",
        received_on="2024-03-01",
        priority_filter="medium",
    )
    assert q.startswith("subject:pay")
    assert "read:no" in q
    assert "received:2024-03-01..2024-03-01" in q
    assert "importance:normal" in q


def test_search_kql_open_ended_after() -> None:
    q = build_search_kql_query("*", read_filter="any", received_after="2024-06-01")
    assert "received:2024-06-01..2099-12-31" in q


def test_search_kql_invalid_read_filter() -> None:
    with pytest.raises(ValueError, match="read_filter"):
        build_search_kql_query("a", read_filter="maybe")
