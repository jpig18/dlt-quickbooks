"""dlt source for QuickBooks Online.

Full-coverage source for the QuickBooks Online Accounting API: all queryable
entities with incremental loading on ``Metadata.LastUpdatedTime``, rotating
refresh-token auth, and QBO-native pagination. Companion sources for CDC,
reports, attachments, and the Payments API live alongside in this package.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, cast

import dlt
import pendulum
from dlt.sources import DltResource
from dlt.sources.helpers import requests as dlt_requests
from dlt.sources.helpers.rest_client.client import RESTClient
from dlt.sources.rest_api import rest_api_resources
from dlt.sources.rest_api.typing import RESTAPIConfig

from .helpers.auth import FileTokenStore, QboRefreshTokenAuth, TokenStore
from .helpers.cdc import CDC_MAX_LOOKBACK_DAYS, clamp_changed_since, parse_cdc_response
from .helpers.files import sanitize_filename, write_bytes
from .helpers.paginator import QboQueryPaginator
from .helpers.reports import flatten_report
from .settings import (
    BASE_URLS,
    DEFAULT_INITIAL_TIMESTAMP,
    ENTITIES,
    MINOR_VERSION,
    REPORTS,
    to_snake_case,
)

__all__ = [
    "FileTokenStore",
    "QboRefreshTokenAuth",
    "TokenStore",
    "quickbooks",
    "quickbooks_cdc",
    "quickbooks_files",
    "quickbooks_reports",
]

# Entities whose transaction PDFs can be fetched via GET /{entity}/{id}/pdf.
PDF_ENTITIES_DEFAULT = ("Invoice", "Estimate", "SalesReceipt", "CreditMemo")


def _build_auth(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_store_path: str | None,
    token_store: TokenStore | None,
) -> QboRefreshTokenAuth:
    return QboRefreshTokenAuth(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        token_store=token_store
        or (FileTokenStore(token_store_path) if token_store_path else None),
    )


@dlt.source(name="quickbooks", max_table_nesting=2)
def quickbooks(
    client_id: str = dlt.secrets.value,
    client_secret: str = dlt.secrets.value,
    refresh_token: str = dlt.secrets.value,
    realm_id: str = dlt.secrets.value,
    environment: str = "production",
    token_store_path: str | None = "qbo_token.json",
    token_store: TokenStore | None = None,
    entities: list[str] | None = None,
    initial_timestamp: str = DEFAULT_INITIAL_TIMESTAMP,
) -> Iterable[DltResource]:
    """All queryable QuickBooks Online Accounting API entities.

    Entities that support ``Metadata.LastUpdatedTime`` filtering load
    incrementally with ``write_disposition="merge"`` on ``Id``; singletons and
    entities without a stable cursor load with ``replace``. Hard deletes never
    appear in query results — pair with the CDC source to capture them.

    Args:
        client_id: Intuit app OAuth2 client id.
        client_secret: Intuit app OAuth2 client secret.
        refresh_token: Initial OAuth2 refresh token (rotated tokens are then
            persisted via the token store).
        realm_id: QuickBooks company id.
        environment: "production" or "sandbox".
        token_store_path: Path for the default file-based token store. Ignored
            when ``token_store`` is given.
        token_store: Custom ``TokenStore`` implementation (e.g. backed by a
            secret manager) for persisting rotated refresh tokens.
        entities: Optional subset of entities to load, by API name
            ("Invoice") or resource name ("invoice").
        initial_timestamp: Lower bound for the first incremental load,
            ISO 8601.

    Yields:
        One dlt resource per configured entity.
    """
    auth = _build_auth(
        client_id, client_secret, refresh_token, token_store_path, token_store
    )

    selected: set[str] | None = None
    if entities is not None:
        selected = {to_snake_case(e) for e in entities}

    resources: list[dict[str, Any]] = []
    for entity in ENTITIES:
        resource_name = to_snake_case(entity.name)
        if selected is not None and resource_name not in selected:
            continue
        endpoint: dict[str, Any] = {
            "path": "query",
            "params": {"minorversion": MINOR_VERSION},
            "data_selector": f"QueryResponse.{entity.name}",
            "paginator": QboQueryPaginator(),
        }
        if entity.incremental:
            endpoint["params"]["query"] = (
                f"SELECT * FROM {entity.name}"
                " WHERE Metadata.LastUpdatedTime >= '{incremental.start_value}'"
                " ORDERBY Metadata.LastUpdatedTime"
            )
            endpoint["incremental"] = {
                "cursor_path": "MetaData.LastUpdatedTime",
                "initial_value": initial_timestamp,
            }
        else:
            endpoint["params"]["query"] = f"SELECT * FROM {entity.name}"
        resource: dict[str, Any] = {
            "name": resource_name,
            "endpoint": endpoint,
            "write_disposition": "merge" if entity.incremental else "replace",
        }
        if entity.primary_key is not None:
            resource["primary_key"] = entity.primary_key
        resources.append(resource)

    config = cast(
        RESTAPIConfig,
        {
            "client": {
                "base_url": f"{BASE_URLS[environment]}/v3/company/{realm_id}/",
                "auth": auth,
                "headers": {"Accept": "application/json"},
            },
            "resources": resources,
        },
    )
    yield from rest_api_resources(config)


# The CDC source shares the schema name ("quickbooks") and config section with
# the core source so its rows merge into the same per-entity tables.
@dlt.source(name="quickbooks", section="quickbooks", max_table_nesting=2)
def quickbooks_cdc(
    client_id: str = dlt.secrets.value,
    client_secret: str = dlt.secrets.value,
    refresh_token: str = dlt.secrets.value,
    realm_id: str = dlt.secrets.value,
    environment: str = "production",
    token_store_path: str | None = "qbo_token.json",
    token_store: TokenStore | None = None,
    entities: list[str] | None = None,
    initial_changed_since: str | None = None,
    lookback_days: int = CDC_MAX_LOOKBACK_DAYS,
) -> Iterable[DltResource]:
    """Change Data Capture: adds, updates, and hard deletes since the last run.

    Fetches ``/cdc`` for all CDC-eligible entities and dispatches rows into the
    same tables as the core ``quickbooks`` source (merge on ``Id``). Deleted
    records arrive as minimal objects and are flagged with ``_qbo_deleted=True``
    (their other columns become NULL on merge). Intended operating pattern:
    one full load with ``quickbooks()``, then frequent ``quickbooks_cdc()`` runs
    — CDC also captures hard deletes, which query-based loads never see.

    Args:
        client_id: Intuit app OAuth2 client id.
        client_secret: Intuit app OAuth2 client secret.
        refresh_token: Initial OAuth2 refresh token.
        realm_id: QuickBooks company id.
        environment: "production" or "sandbox".
        token_store_path: Path for the default file-based token store. Ignored
            when ``token_store`` is given.
        token_store: Custom ``TokenStore`` implementation.
        entities: Optional subset of CDC-eligible entities, by API name
            ("Invoice") or resource name ("invoice").
        initial_changed_since: ISO 8601 lower bound for the first run.
            Defaults to ``lookback_days`` ago (the CDC maximum).
        lookback_days: CDC lookback window; Intuit rejects anything over 30.

    Yields:
        A single resource that dispatches rows to per-entity tables.
    """
    auth = _build_auth(
        client_id, client_secret, refresh_token, token_store_path, token_store
    )
    client = RESTClient(
        base_url=f"{BASE_URLS[environment]}/v3/company/{realm_id}/",
        auth=auth,
        headers={"Accept": "application/json"},
    )

    cdc_entities = [e.name for e in ENTITIES if e.cdc]
    if entities is not None:
        selected = {to_snake_case(e) for e in entities}
        cdc_entities = [n for n in cdc_entities if to_snake_case(n) in selected]

    initial = (
        initial_changed_since
        or pendulum.now("UTC").subtract(days=lookback_days).isoformat()
    )

    @dlt.resource(
        name="qbo_cdc",
        table_name=lambda row: to_snake_case(cast(str, row["_qbo_entity"])),
        primary_key="Id",
        write_disposition="merge",
    )
    def cdc(
        changed_since: dlt.sources.incremental[str] = dlt.sources.incremental(
            "MetaData.LastUpdatedTime",
            initial_value=initial,
            on_cursor_value_missing="include",
        ),
    ) -> Iterator[dict[str, Any]]:
        since = clamp_changed_since(changed_since.start_value or initial, lookback_days)
        response = client.get(
            "cdc",
            params={
                "entities": ",".join(cdc_entities),
                "changedSince": since,
                "minorversion": MINOR_VERSION,
            },
        )
        response.raise_for_status()
        for entity_name, record in parse_cdc_response(response.json()):
            record["_qbo_entity"] = entity_name
            record["_qbo_deleted"] = record.get("status") == "Deleted"
            yield record

    yield cdc


@dlt.source(name="quickbooks", section="quickbooks", max_table_nesting=0)
def quickbooks_reports(
    client_id: str = dlt.secrets.value,
    client_secret: str = dlt.secrets.value,
    refresh_token: str = dlt.secrets.value,
    realm_id: str = dlt.secrets.value,
    environment: str = "production",
    token_store_path: str | None = "qbo_token.json",
    token_store: TokenStore | None = None,
    reports: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    report_params: dict[str, dict[str, str]] | None = None,
) -> Iterable[DltResource]:
    """Computed financial reports (P&L, Balance Sheet, GL, agings, …).

    Each report loads into its own ``report_<name>`` table with
    ``write_disposition="replace"``: reports are computed views over a period,
    not entities, so every run replaces the table with the freshly generated
    report. Snapshot downstream (or window with ``start_date``/``end_date``
    per run) if you need report history. Responses are capped by Intuit at
    400,000 cells — window large reports (e.g. GeneralLedger) by date.

    Args:
        client_id: Intuit app OAuth2 client id.
        client_secret: Intuit app OAuth2 client secret.
        refresh_token: Initial OAuth2 refresh token.
        realm_id: QuickBooks company id.
        environment: "production" or "sandbox".
        token_store_path: Path for the default file-based token store. Ignored
            when ``token_store`` is given.
        token_store: Custom ``TokenStore`` implementation.
        reports: Report names to load (see ``settings.REPORTS``). Defaults to
            every report in the registry; reports a company has no data for
            simply produce empty tables.
        start_date: Optional ``start_date`` param applied to all reports
            (YYYY-MM-DD). Without it, QBO defaults each report's period.
        end_date: Optional ``end_date`` param applied to all reports.
        report_params: Per-report query-param overrides, keyed by report name,
            e.g. ``{"ProfitAndLoss": {"summarize_column_by": "Month"}}``.
            Merged over ``start_date``/``end_date``.

    Yields:
        One dlt resource per report.
    """
    auth = _build_auth(
        client_id, client_secret, refresh_token, token_store_path, token_store
    )
    client = RESTClient(
        base_url=f"{BASE_URLS[environment]}/v3/company/{realm_id}/",
        auth=auth,
        headers={"Accept": "application/json"},
    )

    selected_reports = list(REPORTS)
    if reports is not None:
        registry = {r.lower(): r for r in REPORTS}
        selected_reports = [registry.get(r.lower(), r) for r in reports]

    def make_report_resource(report_name: str, params: dict[str, str]) -> DltResource:
        def fetch_report() -> Iterator[dict[str, Any]]:
            response = client.get(f"reports/{report_name}", params=params)
            response.raise_for_status()
            yield from flatten_report(response.json())

        return dlt.resource(
            fetch_report,
            name=f"report_{to_snake_case(report_name)}",
            write_disposition="replace",
        )

    for report_name in selected_reports:
        params: dict[str, str] = {"minorversion": MINOR_VERSION}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        params.update((report_params or {}).get(report_name, {}))
        yield make_report_resource(report_name, params)


@dlt.source(name="quickbooks", section="quickbooks", max_table_nesting=2)
def quickbooks_files(
    files_url: str,
    client_id: str = dlt.secrets.value,
    client_secret: str = dlt.secrets.value,
    refresh_token: str = dlt.secrets.value,
    realm_id: str = dlt.secrets.value,
    environment: str = "production",
    token_store_path: str | None = "qbo_token.json",
    token_store: TokenStore | None = None,
    pdf_entities: list[str] | None = None,
    initial_timestamp: str = DEFAULT_INITIAL_TIMESTAMP,
) -> Iterable[DltResource]:
    """Attachable file binaries and transaction PDFs.

    Two resources:

    - ``attachable``: Attachable metadata (merged into the same table the core
      source loads) with each binary downloaded via its ``TempDownloadUri`` to
      ``{files_url}/attachable/{Id}/{FileName}`` and recorded in
      ``_qbo_file_path``. Note-only attachables (no file) are skipped.
    - ``entity_pdf``: the QBO-rendered PDF for each transaction of the
      configured entity types, downloaded to
      ``{files_url}/pdf/{entity}/{Id}.pdf`` with one metadata row per file.

    Both resources load incrementally on ``Metadata.LastUpdatedTime``, so only
    new/updated files are downloaded on re-runs.

    Args:
        files_url: fsspec-compatible base URL for binaries — a local directory
            path, ``s3://bucket/prefix``, ``gs://…``, etc.
        client_id: Intuit app OAuth2 client id.
        client_secret: Intuit app OAuth2 client secret.
        refresh_token: Initial OAuth2 refresh token.
        realm_id: QuickBooks company id.
        environment: "production" or "sandbox".
        token_store_path: Path for the default file-based token store. Ignored
            when ``token_store`` is given.
        token_store: Custom ``TokenStore`` implementation.
        pdf_entities: Entity types to fetch PDFs for. Defaults to Invoice,
            Estimate, SalesReceipt, and CreditMemo.
        initial_timestamp: Lower bound for the first incremental load,
            ISO 8601.

    Yields:
        The ``attachable`` and ``entity_pdf`` resources.
    """
    auth = _build_auth(
        client_id, client_secret, refresh_token, token_store_path, token_store
    )
    client = RESTClient(
        base_url=f"{BASE_URLS[environment]}/v3/company/{realm_id}/",
        auth=auth,
        headers={"Accept": "application/json"},
    )

    def query_pages(query: str) -> Iterator[list[dict[str, Any]]]:
        entity_name = query.split(" FROM ")[1].split(" ")[0]
        yield from client.paginate(
            "query",
            params={"query": query, "minorversion": MINOR_VERSION},
            paginator=QboQueryPaginator(),
            data_selector=f"QueryResponse.{entity_name}",
        )

    @dlt.resource(name="attachable", primary_key="Id", write_disposition="merge")
    def attachables(
        updated: dlt.sources.incremental[str] = dlt.sources.incremental(
            "MetaData.LastUpdatedTime", initial_value=initial_timestamp
        ),
    ) -> Iterator[dict[str, Any]]:
        query = (
            "SELECT * FROM Attachable"
            f" WHERE Metadata.LastUpdatedTime >= '{updated.start_value}'"
            " ORDERBY Metadata.LastUpdatedTime"
        )
        for page in query_pages(query):
            for record in page:
                download_uri = record.get("TempDownloadUri")
                if download_uri:
                    file_name = sanitize_filename(
                        record.get("FileName") or record["Id"]
                    )
                    content = dlt_requests.get(download_uri).content
                    record["_qbo_file_path"] = write_bytes(
                        files_url, f"attachable/{record['Id']}/{file_name}", content
                    )
                yield record

    @dlt.resource(
        name="entity_pdf", primary_key=("entity", "id"), write_disposition="merge"
    )
    def entity_pdfs(
        updated: dlt.sources.incremental[str] = dlt.sources.incremental(
            "last_updated_time", initial_value=initial_timestamp
        ),
    ) -> Iterator[dict[str, Any]]:
        for entity_name in pdf_entities or list(PDF_ENTITIES_DEFAULT):
            query = (
                f"SELECT Id, Metadata.LastUpdatedTime FROM {entity_name}"
                f" WHERE Metadata.LastUpdatedTime >= '{updated.start_value}'"
                " ORDERBY Metadata.LastUpdatedTime"
            )
            for page in query_pages(query):
                for record in page:
                    entity_id = record["Id"]
                    response = client.get(
                        f"{entity_name.lower()}/{entity_id}/pdf",
                        params={"minorversion": MINOR_VERSION},
                        headers={"Accept": "application/pdf"},
                    )
                    response.raise_for_status()
                    path = write_bytes(
                        files_url,
                        f"pdf/{entity_name.lower()}/{entity_id}.pdf",
                        response.content,
                    )
                    yield {
                        "entity": entity_name,
                        "id": entity_id,
                        "last_updated_time": record.get("MetaData", {}).get(
                            "LastUpdatedTime"
                        ),
                        "_qbo_file_path": path,
                    }

    yield attachables
    yield entity_pdfs
