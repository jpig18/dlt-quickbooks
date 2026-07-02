"""Flattener for QuickBooks Reports API responses.

Report responses are not entity lists: they arrive as a nested
Header/Columns/Rows envelope where sections contain rows (and sub-sections)
plus summary rows. This module converts that envelope into flat records, one
per data/summary row, with column names derived from the report's column
headers and a ``section_path`` breadcrumb preserving the hierarchy.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any


def _column_key(title: str, col_type: str, index: int, seen: set[str]) -> str:
    """Derive a stable snake_case column key from a report column header."""
    base = title.strip() or col_type.strip() or f"col_{index}"
    key = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or f"col_{index}"
    if key in seen:
        key = f"{key}_{index}"
    seen.add(key)
    return key


def _column_keys(payload: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    columns = payload.get("Columns", {}).get("Column", [])
    return [
        _column_key(col.get("ColTitle", ""), col.get("ColType", ""), i, seen)
        for i, col in enumerate(columns)
    ]


def _report_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    header = payload.get("Header", {})
    return {
        "report_name": header.get("ReportName"),
        "start_period": header.get("StartPeriod"),
        "end_period": header.get("EndPeriod"),
        "currency": header.get("Currency"),
        "report_basis": header.get("ReportBasis"),
        "generated_at": header.get("Time"),
    }


def _row_record(
    col_data: list[dict[str, Any]],
    columns: list[str],
    row_type: str,
    section_path: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        **metadata,
        "row_type": row_type,
        "section_path": " > ".join(section_path) if section_path else None,
    }
    for i, cell in enumerate(col_data):
        key = columns[i] if i < len(columns) else f"col_{i}"
        record[key] = cell.get("value")
        # cells referencing entities (accounts, customers, …) carry their Id
        if cell.get("id"):
            record[f"{key}_id"] = cell["id"]
    return record


def _walk_rows(
    rows: list[dict[str, Any]],
    columns: list[str],
    section_path: list[str],
    metadata: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    for row in rows:
        row_type = row.get("type", "Data")
        if row_type == "Section" or "Rows" in row or "Header" in row:
            header_cells = row.get("Header", {}).get("ColData", [])
            section_title = (
                str(header_cells[0].get("value", "")) if header_cells else ""
            )
            child_path = (
                [*section_path, section_title] if section_title else section_path
            )
            if header_cells:
                yield _row_record(
                    header_cells, columns, "SectionHeader", section_path, metadata
                )
            yield from _walk_rows(
                row.get("Rows", {}).get("Row", []), columns, child_path, metadata
            )
            summary_cells = row.get("Summary", {}).get("ColData", [])
            if summary_cells:
                yield _row_record(
                    summary_cells, columns, "Summary", child_path, metadata
                )
        elif "ColData" in row:
            yield _row_record(row["ColData"], columns, row_type, section_path, metadata)


def flatten_report(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield one flat record per report row (data, section header, or summary).

    Every record carries the report metadata (name, period, currency, basis,
    generation time), a ``row_type``, a ``section_path`` breadcrumb, one column
    per report column header, and ``<column>_id`` columns for cells that
    reference entities.
    """
    columns = _column_keys(payload)
    metadata = _report_metadata(payload)
    yield from _walk_rows(payload.get("Rows", {}).get("Row", []), columns, [], metadata)
