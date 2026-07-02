from pathlib import Path
from typing import Any

import dlt
import pendulum

from quickbooks import quickbooks_cdc
from quickbooks.helpers.cdc import clamp_changed_since, parse_cdc_response
from quickbooks.settings import INTUIT_TOKEN_URL
from tests.utils import assert_load_info

CDC_PAYLOAD: dict[str, Any] = {
    "CDCResponse": [
        {
            "QueryResponse": [
                {
                    "Invoice": [
                        {
                            "Id": "101",
                            "TotalAmt": 250.0,
                            "MetaData": {
                                "LastUpdatedTime": "2026-07-01T10:00:00-07:00"
                            },
                        }
                    ],
                    "startPosition": 1,
                    "maxResults": 1,
                },
                {
                    "Customer": [
                        {
                            "Id": "42",
                            "status": "Deleted",
                            "domain": "QBO",
                            "MetaData": {
                                "LastUpdatedTime": "2026-07-01T11:00:00-07:00"
                            },
                        }
                    ]
                },
            ]
        }
    ],
    "time": "2026-07-02T00:00:00-07:00",
}


def test_parse_cdc_response_yields_entity_records() -> None:
    records = list(parse_cdc_response(CDC_PAYLOAD))
    assert (
        "Invoice",
        CDC_PAYLOAD["CDCResponse"][0]["QueryResponse"][0]["Invoice"][0],
    ) in records
    entity_names = [name for name, _ in records]
    assert entity_names == ["Invoice", "Customer"]


def test_parse_cdc_response_empty_payload() -> None:
    assert list(parse_cdc_response({"time": "2026-07-02T00:00:00-07:00"})) == []


def test_clamp_changed_since_keeps_recent_values() -> None:
    recent = pendulum.now("UTC").subtract(days=2).isoformat()
    assert clamp_changed_since(recent, lookback_days=30) == recent


def test_clamp_changed_since_clamps_old_values() -> None:
    stale = pendulum.now("UTC").subtract(days=90).isoformat()
    clamped = pendulum.parse(clamp_changed_since(stale, lookback_days=30))
    assert isinstance(clamped, pendulum.DateTime)
    assert clamped > pendulum.now("UTC").subtract(days=31)


def test_cdc_pipeline_merges_and_flags_deletes(
    requests_mock: Any, tmp_path: Path
) -> None:
    requests_mock.post(
        INTUIT_TOKEN_URL,
        json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
    )
    cdc_mock = requests_mock.get(
        "https://sandbox-quickbooks.api.intuit.com/v3/company/123/cdc",
        json=CDC_PAYLOAD,
    )

    pipeline = dlt.pipeline(
        pipeline_name="qbo_cdc_test",
        destination=dlt.destinations.duckdb(str(tmp_path / "test.duckdb")),
        dataset_name="qbo",
        dev_mode=True,
    )
    load_info = pipeline.run(
        quickbooks_cdc(
            client_id="cid",
            client_secret="cs",
            refresh_token="rt",
            realm_id="123",
            environment="sandbox",
            token_store_path=str(tmp_path / "token.json"),
        )
    )
    assert_load_info(load_info)

    with pipeline.sql_client() as client:
        invoices = client.execute_sql(
            "select id, _qbo_deleted, _qbo_entity from invoice"
        )
        customers = client.execute_sql(
            "select id, _qbo_deleted, _qbo_entity from customer"
        )
    assert invoices == [("101", False, "Invoice")]
    assert customers == [("42", True, "Customer")]

    # the CDC request carried the entity CSV and a changedSince param
    cdc_request = cdc_mock.last_request
    assert "changedsince" in cdc_request.qs
    assert "invoice" in cdc_request.qs["entities"][0].lower()
