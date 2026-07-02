# dlt-quickbooks

A [dlt](https://dlthub.com) source for **QuickBooks Online** with full API coverage — built to
[dlt-hub/verified-sources](https://github.com/dlt-hub/verified-sources) standards.

| Source | What it pulls | Tables |
|---|---|---|
| `quickbooks()` | All 36 queryable Accounting API entities, incremental on `Metadata.LastUpdatedTime` | one per entity (`invoice`, `customer`, …) |
| `quickbooks_cdc()` | Change Data Capture: adds, updates, and **hard deletes** since the last run | merges into the same entity tables, flags `_qbo_deleted` |
| `quickbooks_reports()` | 28 computed reports (P&L, Balance Sheet, GL, Trial Balance, agings, …) flattened to tabular rows | `report_<name>` |
| `quickbooks_files()` | Attachment binaries + transaction PDFs to any fsspec URL (local, `s3://`, `gs://`) | `attachable`, `entity_pdf` (+ files) |
| `quickbooks_payments()` | Stored payment methods per customer (QuickBooks Payments) | `payment_card`, `payment_bank_account` |

Plus the operational plumbing QBO actually requires:

- **Rotating refresh tokens** — Intuit rotates the refresh token ~daily; a static credential
  silently breaks. `QboRefreshTokenAuth` persists rotated tokens via a pluggable `TokenStore`
  (file-based by default; implement the 2-method protocol against your secret manager for prod).
- **QBO-native pagination** — `STARTPOSITION`/`MAXRESULTS` inside the query dialect, 1000-row pages.
- **Incremental by default** — merge on `Id` + `Metadata.LastUpdatedTime` cursor. Re-runs pull only
  changes, which also matters for Intuit's metered API pricing.
- Retry/backoff on 429s (500 req/min per realm), `minorversion=75` (the post-Aug-2025 baseline),
  sandbox/production switch.

Not covered by design: the **Payroll API** (partner-gated) and **Webhooks** (push-based — run
`quickbooks_cdc()` on a tight schedule instead). Payments charges/refunds/e-checks have no list
endpoints (retrieve-by-id only); their ledger impact flows through the Accounting entities.

## Install

```sh
# as a verified-sources-style scaffold (copies sources/quickbooks into your pipeline project)
dlt init quickbooks duckdb --location https://github.com/jpig18/dlt-quickbooks

# or as a package
pip install "dlt-quickbooks @ git+https://github.com/jpig18/dlt-quickbooks"
```

## Authentication

You need an Intuit developer app (free) and, for testing, a sandbox company:

1. Create an app at <https://developer.intuit.com> → `client_id` / `client_secret`.
2. Mint an initial `refresh_token` with the
   [OAuth 2.0 Playground](https://developer.intuit.com/app/developer/playground)
   (scope `com.intuit.quickbooks.accounting`; add `com.intuit.quickbooks.payment` for the
   payments source).
3. Note the company's `realm_id` (shown in the playground).

Configure `.dlt/secrets.toml` (template: `.dlt/secrets.toml.example`):

```toml
[sources.quickbooks]
client_id = "..."
client_secret = "..."
refresh_token = "..."
realm_id = "..."
environment = "sandbox"   # or "production"
```

> **Token rotation.** On the first refresh Intuit may return a *new* refresh token which must be
> used from then on. The source stores rotated tokens in `qbo_token.json` by default
> (`token_store_path`); the stored token supersedes `secrets.toml` on later runs. For scheduled
> production pipelines implement `TokenStore` (`load()`/`save()`) against your secret manager —
> see `sources/quickbooks/helpers/auth.py`.

## Usage

```python
import dlt
from quickbooks import quickbooks, quickbooks_cdc, quickbooks_reports

pipeline = dlt.pipeline(pipeline_name="quickbooks", destination="duckdb", dataset_name="qbo")

# full load, incremental on re-runs
pipeline.run(quickbooks())

# frequent syncs between full loads: adds/updates/hard-deletes (_qbo_deleted=True)
pipeline.run(quickbooks_cdc())

# computed reports for a window
pipeline.run(quickbooks_reports(reports=["ProfitAndLoss", "BalanceSheet"],
                                start_date="2026-01-01", end_date="2026-06-30"))
```

More examples (entity subsets, file downloads, payment methods) in
`sources/quickbooks_pipeline.py`.

**Operating pattern:** run `quickbooks()` for the initial backfill, then schedule
`quickbooks_cdc()` frequently (CDC looks back at most 30 days — don't let it lapse longer, or
re-run a full load). Reports replace their tables each run; snapshot downstream if you need
report history.

## Entity coverage

Name lists: Account, Budget, Class, CompanyCurrency, Customer, CustomerType, Department,
Employee, Item, PaymentMethod, TaxAgency, TaxCode, TaxRate, Term, Vendor.
Transactions: Bill, BillPayment, CreditCardPayment, CreditMemo, Deposit, Estimate, Invoice,
JournalEntry, Payment, Purchase, PurchaseOrder, RecurringTransaction, RefundReceipt,
SalesReceipt, TimeActivity, Transfer, VendorCredit.
Supporting: Attachable, CompanyInfo, ExchangeRate, Preferences.

Reports: AccountList, AgedPayableDetail, AgedPayables, AgedReceivableDetail, AgedReceivables,
BalanceSheet, CashFlow, ClassSales, CustomerBalance, CustomerBalanceDetail, CustomerIncome,
CustomerSales, DepartmentSales, GeneralLedger, InventoryValuationDetail,
InventoryValuationSummary, ItemSales, JournalReport, ProfitAndLoss, ProfitAndLossDetail,
TaxSummary, TransactionList, TransactionListByCustomer, TransactionListByVendor, TrialBalance,
VendorBalance, VendorBalanceDetail, VendorExpenses.

## Development

```sh
make install    # uv sync
make check      # ruff + mypy (strict) + unit tests
make test-live  # integration tests against an Intuit sandbox (needs .dlt/secrets.toml)
```

Repo layout follows dlt-hub/verified-sources conventions (`sources/quickbooks/`,
`sources/quickbooks_pipeline.py`, `tests/quickbooks/`) so it can be consumed via
`dlt init --location` and upstreamed.

## License

Apache-2.0
