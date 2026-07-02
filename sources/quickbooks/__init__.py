"""dlt source for QuickBooks Online.

Full-coverage source for the QuickBooks Online Accounting API: all queryable
entities with incremental loading on ``Metadata.LastUpdatedTime``, rotating
refresh-token auth, and QBO-native pagination. Companion sources for CDC,
reports, attachments, and the Payments API live alongside in this package.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import dlt
from dlt.sources import DltResource
from dlt.sources.rest_api import rest_api_resources
from dlt.sources.rest_api.typing import RESTAPIConfig

from .helpers.auth import FileTokenStore, QboRefreshTokenAuth, TokenStore
from .helpers.paginator import QboQueryPaginator
from .settings import (
    BASE_URLS,
    DEFAULT_INITIAL_TIMESTAMP,
    ENTITIES,
    MINOR_VERSION,
    to_snake_case,
)

__all__ = ["FileTokenStore", "QboRefreshTokenAuth", "TokenStore", "quickbooks"]


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
    auth = QboRefreshTokenAuth(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        token_store=token_store
        or (FileTokenStore(token_store_path) if token_store_path else None),
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
