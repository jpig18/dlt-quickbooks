# Draft: new verified source issue for dlt-hub/verified-sources

> Post to: https://github.com/dlt-hub/verified-sources/issues/new
> Title: **[new source] QuickBooks Online**

## Source description

QuickBooks Online — Intuit's small-business accounting platform. This source
covers the full read surface of the QuickBooks Online API:

- **All 36 queryable Accounting API entities** (Customer, Invoice, Bill,
  JournalEntry, Account, Item, …) with incremental loading on
  `Metadata.LastUpdatedTime` (`merge` on `Id`), via the declarative `rest_api`
  toolkit with a small custom paginator (QBO paginates with
  `STARTPOSITION`/`MAXRESULTS` clauses *inside* its SQL-like query parameter).
- **Change Data Capture** (`/cdc`): adds, updates, and hard deletes (flagged
  `_qbo_deleted`) merged into the same entity tables — the only way to observe
  deletes without full reloads.
- **Reports API**: 28 computed reports (P&L, Balance Sheet, General Ledger,
  Trial Balance, agings, …) flattened from the nested Rows/Columns envelope
  into tabular rows with section breadcrumbs.
- **Files**: Attachable binaries and transaction PDFs downloaded to any fsspec
  URL, with metadata rows.
- **Payments API**: stored cards/bank accounts per customer.
- **Rotating refresh-token auth**: Intuit rotates refresh tokens ~daily; the
  auth class (an `OAuth2ClientCredentials` subclass) persists rotated tokens
  via a pluggable token store, so scheduled pipelines don't silently break.

## Why this can't be a plain `rest_api` config

I know new sources are only accepted when they can't be easily implemented
with the REST API toolkit alone. QuickBooks looks like a REST API source but
four things require real custom code, and each is a trap people fall into:

1. **Auth is stateful.** Intuit *rotates* the refresh token roughly every 24h;
   the rotated value must be persisted and used next time or the pipeline
   silently dies within days. That needs a custom `OAuth2ClientCredentials`
   subclass with a token-store hook — not expressible in config.
2. **Pagination lives inside a query dialect.** `STARTPOSITION`/`MAXRESULTS`
   are clauses of QBO's SQL-like `query` string parameter, not request params —
   no built-in paginator applies; a custom `BasePaginator` rewrites the query.
3. **Deletes are only visible via `/cdc`**, whose response is a per-entity
   envelope with deletion markers that must be dispatched into the entity
   tables as soft-deletes. Query-based loads never see hard deletes.
4. **The Reports API isn't records.** Responses are a nested
   Header/Columns/Rows envelope needing a recursive flattener (section
   breadcrumbs, summary rows, per-column keys, entity-id cells).

There is currently no QuickBooks source in verified-sources, and QBO's metered
API pricing (2025) makes correct incremental loading a cost feature, not just
a performance one.

## Implementation

Working implementation, built to this repo's CONTRIBUTING conventions
(self-contained source dir, typed, Google docstrings, demo pipeline, tests):
https://github.com/jpig18/dlt-quickbooks

- `sources/quickbooks/` — source package (declarative rest_api core + custom
  auth/paginator/CDC/report-flattener helpers in `helpers/`)
- `sources/quickbooks_pipeline.py` — demo pipeline
- `tests/quickbooks/` — unit tests (mocked HTTP, including full pipeline runs
  into duckdb) + live sandbox suite (marked, skipped without credentials)

Happy to open the PR. For CI: Intuit developer accounts are free and include
a permanent sandbox company with seed data — we can provide sandbox
credentials for `DLT_SECRETS_TOML`, or the team can mint their own in a few
minutes via Intuit's OAuth 2.0 Playground.

## Credentials needed for testing

`client_id`, `client_secret`, `refresh_token` (OAuth2, scope
`com.intuit.quickbooks.accounting`; optionally `com.intuit.quickbooks.payment`),
`realm_id`, `environment = "sandbox"`.
