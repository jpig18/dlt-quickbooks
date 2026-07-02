# dlt-quickbooks

A [dlt](https://dlthub.com) source for **QuickBooks Online** with full API coverage:

- **All queryable Accounting API entities** (~40: customers, invoices, bills, journal entries, …) with incremental loading on `MetaData.LastUpdatedTime` (`merge` write disposition — re-runs only pull what changed, which also keeps Intuit's metered API costs down)
- **Change Data Capture** (`/cdc`) source for frequent syncs and hard-delete detection
- **Reports API** (~27 computed reports: P&L, Balance Sheet, General Ledger, Trial Balance, agings, …) flattened from Intuit's nested Rows/Columns envelope into tabular rows
- **Attachments & PDFs** — Attachable file binaries and invoice/estimate PDFs downloaded to any fsspec URL (local dir, `s3://…`)
- **Payments API** (charges, refunds, cards, e-checks) as a separate source
- **Rotating refresh-token handling** — QBO rotates refresh tokens (~daily); the source persists rotated tokens via a pluggable token store so long-running schedules don't silently break

Not covered by design: the Payroll API (partner-gated) and Webhooks (push-based; use the CDC source instead).

## Quick start

```sh
# as a verified-sources-style scaffold
dlt init quickbooks duckdb --location https://github.com/jpig18/dlt-quickbooks

# or as a package
pip install "dlt-quickbooks @ git+https://github.com/jpig18/dlt-quickbooks"
```

Configure credentials in `.dlt/secrets.toml` (see `.dlt/secrets.toml.example`), then:

```python
import dlt
from quickbooks import quickbooks

pipeline = dlt.pipeline(pipeline_name="qbo", destination="duckdb", dataset_name="quickbooks")
info = pipeline.run(quickbooks())
print(info)
```

See `sources/quickbooks_pipeline.py` for runnable examples of every source
(`quickbooks`, `quickbooks_cdc`, `quickbooks_reports`, `quickbooks_payments`).

## Authentication

You need an Intuit developer app (free) and, for testing, a sandbox company:

1. Create an app at <https://developer.intuit.com> → get `client_id` / `client_secret`.
2. Mint an initial `refresh_token` with the [OAuth 2.0 Playground](https://developer.intuit.com/app/developer/playground) (scope `com.intuit.quickbooks.accounting`).
3. Note your company's `realm_id` (shown in the playground / company settings).

> **Rotating refresh tokens.** Intuit rotates the refresh token roughly every
> 24 h; the rotated value must be used for the next refresh. This source
> persists rotated tokens to a token store (default: a local JSON file at
> `token_store_path`). For production schedules, implement the `TokenStore`
> protocol against your secret manager — see `sources/quickbooks/helpers/auth.py`.

## Development

```sh
make install    # uv sync
make check      # lint + typecheck + unit tests
make test-live  # integration tests (requires sandbox credentials in .dlt/secrets.toml)
```

## Status

Under active development. Resource matrix and per-source docs land as each
phase completes.

## License

Apache-2.0
