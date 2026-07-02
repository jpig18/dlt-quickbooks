"""Demo pipeline for the QuickBooks Online source.

Configure credentials in ``.dlt/secrets.toml`` (see ``.dlt/secrets.toml.example``)
then run: ``python sources/quickbooks_pipeline.py``.
"""

from __future__ import annotations

import dlt

from quickbooks import quickbooks


def load_everything() -> None:
    """Load all Accounting API entities into DuckDB (incremental on re-runs)."""
    pipeline = dlt.pipeline(
        pipeline_name="quickbooks",
        destination="duckdb",
        dataset_name="quickbooks_data",
        progress="log",
    )
    load_info = pipeline.run(quickbooks())
    print(load_info)


def load_selected_entities() -> None:
    """Load only a subset of entities."""
    pipeline = dlt.pipeline(
        pipeline_name="quickbooks",
        destination="duckdb",
        dataset_name="quickbooks_data",
        progress="log",
    )
    load_info = pipeline.run(quickbooks(entities=["Invoice", "Customer", "Payment"]))
    print(load_info)


if __name__ == "__main__":
    load_everything()
