"""Helpers for the QuickBooks Change Data Capture endpoint.

``GET /cdc?entities=<CSV>&changedSince=<ISO8601>`` returns adds, updates, and
deletes for the requested entities within the last 30 days. Deleted records
arrive as minimal objects with ``"status": "Deleted"`` — the only way to
observe hard deletes short of a full reload.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pendulum
from dlt.common import logger

# Bookkeeping keys that appear alongside entity lists in a QueryResponse.
_NON_ENTITY_KEYS = {"startPosition", "maxResults", "totalCount"}

# The CDC endpoint truncates at 1000 objects per entity without pagination.
CDC_TRUNCATION_LIMIT = 1000

# Intuit rejects changedSince values older than 30 days.
CDC_MAX_LOOKBACK_DAYS = 30


def parse_cdc_response(payload: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(entity_name, record)`` pairs from a /cdc response payload."""
    for cdc_response in payload.get("CDCResponse", []):
        for query_response in cdc_response.get("QueryResponse", []):
            for key, value in query_response.items():
                if key in _NON_ENTITY_KEYS or not isinstance(value, list):
                    continue
                if len(value) >= CDC_TRUNCATION_LIMIT:
                    logger.warning(
                        f"CDC response for {key} hit the {CDC_TRUNCATION_LIMIT}-object"
                        " truncation limit; some changes may be missing. Narrow the"
                        " sync window or run a full load of that entity."
                    )
                for record in value:
                    yield key, record


def clamp_changed_since(value: str, lookback_days: int = CDC_MAX_LOOKBACK_DAYS) -> str:
    """Clamp a changedSince timestamp to the CDC lookback window.

    Intuit errors on changedSince older than 30 days. If the stored cursor is
    older (e.g. the pipeline did not run for a while), the window is clamped
    and changes before it are unrecoverable via CDC — a warning recommends a
    full reload in that case.
    """
    floor = pendulum.now("UTC").subtract(days=lookback_days)
    parsed = cast(pendulum.DateTime, pendulum.parse(value))
    if parsed >= floor:
        return value
    # a cursor just past the window (e.g. the default initial value, which is
    # computed moments before this check) is clamped silently
    if floor.diff(parsed).in_minutes() < 60:
        return floor.isoformat()
    logger.warning(
        f"CDC changedSince {value} is older than the {lookback_days}-day lookback"
        f" window; clamping to {floor.isoformat()}. Changes made before that are"
        " not captured — run a full load with the core source to backfill."
    )
    return floor.isoformat()
