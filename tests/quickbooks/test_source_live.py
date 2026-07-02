"""Integration tests against an Intuit sandbox company.

Require ``[sources.quickbooks]`` credentials in ``.dlt/secrets.toml`` (or the
DLT_SECRETS_TOML CI secret) with ``environment = "sandbox"``. Skipped when no
credentials are configured. Sandbox companies ship with seed data across most
entities.
"""

from pathlib import Path

import dlt
import pytest

from quickbooks import quickbooks, quickbooks_reports
from tests.utils import assert_load_info


def _has_credentials() -> bool:
    try:
        dlt.secrets["sources.quickbooks.client_id"]
    except Exception:
        return False
    return True


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _has_credentials(), reason="no sandbox credentials configured"
    ),
]


def _make_pipeline(tmp_path: Path, name: str) -> dlt.Pipeline:
    return dlt.pipeline(
        pipeline_name=name,
        destination=dlt.destinations.duckdb(str(tmp_path / "live.duckdb")),
        dataset_name="qbo_live",
        dev_mode=True,
    )


def test_live_core_entities_and_incremental_rerun(tmp_path: Path) -> None:
    pipeline = _make_pipeline(tmp_path, "qbo_live_core")
    source = quickbooks(
        environment="sandbox",
        entities=["Customer", "Invoice", "Account", "Item"],
        token_store_path=str(tmp_path / "token.json"),
    )
    load_info = pipeline.run(source)
    assert_load_info(load_info)

    with pipeline.sql_client() as client:
        counts = {
            table: client.execute_sql(f"select count(*) from {table}")[0][0]  # type: ignore[index]
            for table in ("customer", "invoice", "account", "item")
        }
    # sandbox companies ship seeded with data in all four
    assert all(count > 0 for count in counts.values()), counts

    # second run is incremental: it must complete and not duplicate rows
    rerun_info = pipeline.run(
        quickbooks(
            environment="sandbox",
            entities=["Customer", "Invoice", "Account", "Item"],
            token_store_path=str(tmp_path / "token.json"),
        )
    )
    assert_load_info(rerun_info)
    with pipeline.sql_client() as client:
        recount = client.execute_sql("select count(*) from customer")[0][0]  # type: ignore[index]
    assert recount == counts["customer"]


def test_live_full_entity_sweep(tmp_path: Path) -> None:
    """Every entity in the registry must be queryable without errors."""
    pipeline = _make_pipeline(tmp_path, "qbo_live_sweep")
    load_info = pipeline.run(
        quickbooks(environment="sandbox", token_store_path=str(tmp_path / "token.json"))
    )
    assert_load_info(load_info)


def test_live_reports(tmp_path: Path) -> None:
    pipeline = _make_pipeline(tmp_path, "qbo_live_reports")
    load_info = pipeline.run(
        quickbooks_reports(
            environment="sandbox",
            reports=["ProfitAndLoss", "BalanceSheet"],
            token_store_path=str(tmp_path / "token.json"),
        )
    )
    assert_load_info(load_info)
    with pipeline.sql_client() as client:
        rows = client.execute_sql("select count(*) from report_profit_and_loss")[0][0]  # type: ignore[index]
    assert rows > 0
