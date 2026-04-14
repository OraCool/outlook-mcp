"""Shared validation and query building for inbox OData filters and search (KQL) clauses."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_received_date_params(
    received_on: str | None,
    received_after: str | None,
    received_before: str | None,
) -> str | None:
    """Return an error message if parameters conflict, else None."""
    if received_on and (received_after or received_before):
        return (
            "Use either received_on (single UTC calendar day) or received_after/received_before, not both."
        )
    return None


def _parse_input_to_utc_datetime(s: str, *, end_of_day_if_date: bool) -> datetime:
    """Parse YYYY-MM-DD (UTC day bounds) or ISO 8601 datetime into UTC aware datetime."""
    s = s.strip()
    if _DATE_ONLY.match(s):
        d = date.fromisoformat(s)
        dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        if end_of_day_if_date:
            return dt + timedelta(days=1)
        return dt
    raw = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _odata(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".0000000Z"


def build_received_datetime_odata_filter(
    received_on: str | None,
    received_after: str | None,
    received_before: str | None,
) -> str | None:
    """Build ``receivedDateTime`` OData predicates for Inbox ``$filter`` (UTC)."""
    err = validate_received_date_params(received_on, received_after, received_before)
    if err:
        raise ValueError(err)

    if received_on:
        if not _DATE_ONLY.match(received_on.strip()):
            raise ValueError("received_on must be YYYY-MM-DD (UTC calendar day).")
        start = _parse_input_to_utc_datetime(received_on, end_of_day_if_date=False)
        end = start + timedelta(days=1)
        return f"receivedDateTime ge {_odata(start)} and receivedDateTime lt {_odata(end)}"

    parts: list[str] = []
    if received_after:
        start = _parse_input_to_utc_datetime(received_after, end_of_day_if_date=False)
        parts.append(f"receivedDateTime ge {_odata(start)}")
    if received_before:
        # Exclusive upper bound: instant before which messages must lie.
        end = _parse_input_to_utc_datetime(received_before, end_of_day_if_date=False)
        parts.append(f"receivedDateTime lt {_odata(end)}")

    if not parts:
        return None
    return " and ".join(parts)


def combine_inbox_odata_filters(*clauses: str | None) -> str | None:
    """Join non-empty clauses with `` and ``."""
    out = [c.strip() for c in clauses if c and str(c).strip()]
    if not out:
        return None
    return " and ".join(out)


def build_inbox_odata_filter(
    unread_only: bool,
    received_on: str | None,
    received_after: str | None,
    received_before: str | None,
) -> str | None:
    """Full ``$filter`` for Inbox list (unread + optional received window)."""
    received = build_received_datetime_odata_filter(
        received_on, received_after, received_before
    )
    unread = "isRead eq false" if unread_only else None
    return combine_inbox_odata_filters(unread, received)


def _assert_kql_date_only(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    if not _DATE_ONLY.match(s):
        raise ValueError(
            f"{name} must be YYYY-MM-DD for search_emails (KQL day granularity in UTC). "
            "Use list_inbox with ISO datetimes for precise bounds."
        )
    return s


def build_received_kql_clause(
    received_on: str | None,
    received_after: str | None,
    received_before: str | None,
) -> str | None:
    """KQL fragment for ``received:`` (mailbox search). Date-only, UTC calendar semantics."""
    err = validate_received_date_params(received_on, received_after, received_before)
    if err:
        raise ValueError(err)

    ro = _assert_kql_date_only("received_on", received_on)
    ra = _assert_kql_date_only("received_after", received_after)
    rb = _assert_kql_date_only("received_before", received_before)

    if ro:
        return f"received:{ro}..{ro}"

    if ra and rb:
        d_a = date.fromisoformat(ra)
        d_b = date.fromisoformat(rb)
        if d_a > d_b:
            raise ValueError("received_after must be on or before received_before.")
        return f"received:{ra}..{rb}"
    if ra:
        return f"received:{ra}..2099-12-31"
    if rb:
        last = date.fromisoformat(rb) - timedelta(days=1)
        lo = date(1970, 1, 1)
        if last < lo:
            raise ValueError(
                "received_before leaves no inclusive UTC day for KQL; use list_inbox with datetimes."
            )
        return f"received:{lo.isoformat()}..{last.isoformat()}"
    return None


def build_search_kql_query(
    query: str,
    *,
    read_filter: str = "any",
    received_on: str | None = None,
    received_after: str | None = None,
    received_before: str | None = None,
) -> str:
    """Combine base KQL with optional read and received constraints."""
    base = query.strip() if query.strip() else "*"
    parts: list[str] = [base]
    if read_filter == "unread":
        parts.append("read:no")
    elif read_filter == "read":
        parts.append("read:yes")
    elif read_filter != "any":
        raise ValueError("read_filter must be any, read, or unread.")

    clause = build_received_kql_clause(received_on, received_after, received_before)
    if clause:
        parts.append(clause)

    return " AND ".join(parts)
