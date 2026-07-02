from pathlib import Path
from typing import Any

import dlt

from quickbooks import quickbooks_payments
from quickbooks.settings import INTUIT_TOKEN_URL
from tests.utils import assert_load_info

ACCOUNTING_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company/123"
PAYMENTS_BASE = "https://sandbox.api.intuit.com/quickbooks/v4/payments"


def test_payments_pipeline_loads_cards_and_bank_accounts(
    requests_mock: Any, tmp_path: Path
) -> None:
    requests_mock.post(
        INTUIT_TOKEN_URL,
        json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
    )
    requests_mock.get(
        f"{ACCOUNTING_BASE}/query",
        json={"QueryResponse": {"Customer": [{"Id": "1"}, {"Id": "2"}]}},
    )
    requests_mock.get(
        f"{PAYMENTS_BASE}/customers/1/cards",
        json=[{"id": "card-1", "number": "xxxxxxxxxxxx1111", "cardType": "Visa"}],
    )
    # customer without stored payment methods
    requests_mock.get(f"{PAYMENTS_BASE}/customers/2/cards", status_code=404)
    requests_mock.get(
        f"{PAYMENTS_BASE}/customers/1/bank-accounts",
        json=[{"id": "bank-1", "accountNumber": "xxxx4321"}],
    )
    requests_mock.get(f"{PAYMENTS_BASE}/customers/2/bank-accounts", json=[])

    pipeline = dlt.pipeline(
        pipeline_name="qbo_payments_test",
        destination=dlt.destinations.duckdb(str(tmp_path / "test.duckdb")),
        dataset_name="qbo",
        dev_mode=True,
    )
    load_info = pipeline.run(
        quickbooks_payments(
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
        cards = client.execute_sql(
            "select id, customer_id, card_type from payment_card"
        )
        banks = client.execute_sql("select id, customer_id from payment_bank_account")
    assert cards == [("card-1", "1", "Visa")]
    assert banks == [("bank-1", "1")]


def test_payments_explicit_customer_ids_skip_accounting_query(
    requests_mock: Any, tmp_path: Path
) -> None:
    requests_mock.post(
        INTUIT_TOKEN_URL,
        json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
    )
    accounting_query = requests_mock.get(f"{ACCOUNTING_BASE}/query", json={})
    requests_mock.get(f"{PAYMENTS_BASE}/customers/9/cards", json=[{"id": "card-9"}])
    requests_mock.get(f"{PAYMENTS_BASE}/customers/9/bank-accounts", json=[])

    pipeline = dlt.pipeline(
        pipeline_name="qbo_payments_test2",
        destination=dlt.destinations.duckdb(str(tmp_path / "test.duckdb")),
        dataset_name="qbo",
        dev_mode=True,
    )
    load_info = pipeline.run(
        quickbooks_payments(
            client_id="cid",
            client_secret="cs",
            refresh_token="rt",
            realm_id="123",
            environment="sandbox",
            token_store_path=str(tmp_path / "token.json"),
            customer_ids=["9"],
        )
    )
    assert_load_info(load_info)
    assert accounting_query.call_count == 0
