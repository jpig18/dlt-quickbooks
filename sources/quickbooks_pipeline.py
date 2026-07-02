"""Demo pipeline for the QuickBooks Online source.

Configure credentials in ``.dlt/secrets.toml`` (see ``.dlt/secrets.toml.example``)
then run: ``python sources/quickbooks_pipeline.py``.
"""

from __future__ import annotations

import dlt

from quickbooks import (
    quickbooks,
    quickbooks_cdc,
    quickbooks_files,
    quickbooks_payments,
    quickbooks_reports,
)


def make_pipeline() -> dlt.Pipeline:
    """All demos share one pipeline/dataset so CDC merges into the core tables."""
    return dlt.pipeline(
        pipeline_name="quickbooks",
        destination="duckdb",
        dataset_name="quickbooks_data",
        progress="log",
    )


def load_everything() -> None:
    """Load all Accounting API entities (incremental on re-runs)."""
    load_info = make_pipeline().run(quickbooks())
    print(load_info)


def load_selected_entities() -> None:
    """Load only a subset of entities."""
    load_info = make_pipeline().run(
        quickbooks(entities=["Invoice", "Customer", "Payment"])
    )
    print(load_info)


def load_changes() -> None:
    """CDC sync: adds, updates, and hard deletes since the last run.

    Run frequently between full loads — deleted records get _qbo_deleted=True.
    """
    load_info = make_pipeline().run(quickbooks_cdc())
    print(load_info)


def load_reports() -> None:
    """Load computed reports (P&L, Balance Sheet, GL, …) for a date window."""
    load_info = make_pipeline().run(
        quickbooks_reports(
            reports=["ProfitAndLoss", "BalanceSheet", "GeneralLedger"],
            start_date="2026-01-01",
            end_date="2026-06-30",
        )
    )
    print(load_info)


def load_files() -> None:
    """Download attachment binaries and invoice/estimate PDFs."""
    load_info = make_pipeline().run(quickbooks_files(files_url="qbo_files"))
    print(load_info)


def load_payment_methods() -> None:
    """Load stored cards and bank accounts (requires QuickBooks Payments)."""
    load_info = make_pipeline().run(quickbooks_payments())
    print(load_info)


if __name__ == "__main__":
    load_everything()
