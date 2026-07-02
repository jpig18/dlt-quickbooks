from pathlib import Path
from typing import Any

import dlt

from quickbooks import quickbooks_files
from quickbooks.helpers.files import sanitize_filename, write_bytes
from quickbooks.settings import INTUIT_TOKEN_URL
from tests.utils import assert_load_info

SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company/123"


def test_sanitize_filename() -> None:
    assert sanitize_filename("receipt.pdf") == "receipt.pdf"
    assert sanitize_filename("a/b\\c.pdf") == "a_b_c.pdf"
    assert sanitize_filename("  ") == "unnamed"


def test_write_bytes_local_roundtrip(tmp_path: Path) -> None:
    destination = write_bytes(str(tmp_path), "attachable/1/receipt.pdf", b"content")
    assert destination == f"{tmp_path}/attachable/1/receipt.pdf"
    assert (tmp_path / "attachable" / "1" / "receipt.pdf").read_bytes() == b"content"


def _query_matcher(entity: str) -> Any:
    def matcher(request: Any) -> bool:
        return f"from {entity.lower()}" in request.qs.get("query", [""])[0].lower()

    return matcher


def test_files_pipeline_downloads_binaries(requests_mock: Any, tmp_path: Path) -> None:
    requests_mock.post(
        INTUIT_TOKEN_URL,
        json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
    )
    requests_mock.get(
        f"{SANDBOX_BASE}/query",
        additional_matcher=_query_matcher("Attachable"),
        json={
            "QueryResponse": {
                "Attachable": [
                    {
                        "Id": "5",
                        "FileName": "receipt one.pdf",
                        "TempDownloadUri": "https://files.example.com/tmp/5",
                        "MetaData": {"LastUpdatedTime": "2026-07-01T10:00:00-07:00"},
                    },
                    # note-only attachable: no file to download
                    {
                        "Id": "6",
                        "Note": "just a note",
                        "MetaData": {"LastUpdatedTime": "2026-07-01T11:00:00-07:00"},
                    },
                ]
            }
        },
    )
    requests_mock.get("https://files.example.com/tmp/5", content=b"%PDF-attachment")
    requests_mock.get(
        f"{SANDBOX_BASE}/query",
        additional_matcher=_query_matcher("Invoice"),
        json={
            "QueryResponse": {
                "Invoice": [
                    {
                        "Id": "101",
                        "MetaData": {"LastUpdatedTime": "2026-07-01T12:00:00-07:00"},
                    }
                ]
            }
        },
    )
    requests_mock.get(f"{SANDBOX_BASE}/invoice/101/pdf", content=b"%PDF-invoice")

    files_dir = tmp_path / "files"
    pipeline = dlt.pipeline(
        pipeline_name="qbo_files_test",
        destination=dlt.destinations.duckdb(str(tmp_path / "test.duckdb")),
        dataset_name="qbo",
        dev_mode=True,
    )
    load_info = pipeline.run(
        quickbooks_files(
            files_url=str(files_dir),
            client_id="cid",
            client_secret="cs",
            refresh_token="rt",
            realm_id="123",
            environment="sandbox",
            token_store_path=str(tmp_path / "token.json"),
            pdf_entities=["Invoice"],
        )
    )
    assert_load_info(load_info)

    # attachment binary written and referenced from the metadata row
    stored = files_dir / "attachable" / "5" / "receipt one.pdf"
    assert stored.read_bytes() == b"%PDF-attachment"
    with pipeline.sql_client() as client:
        attachables = client.execute_sql(
            "select id, _qbo_file_path from attachable order by id"
        )
        pdfs = client.execute_sql("select entity, id, _qbo_file_path from entity_pdf")
    assert attachables is not None
    assert attachables[0] == ("5", str(stored))
    assert attachables[1][0] == "6"
    assert attachables[1][1] is None

    # invoice PDF written and its metadata row recorded
    pdf_path = files_dir / "pdf" / "invoice" / "101.pdf"
    assert pdf_path.read_bytes() == b"%PDF-invoice"
    assert pdfs == [("Invoice", "101", str(pdf_path))]
