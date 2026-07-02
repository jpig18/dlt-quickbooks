"""Constants and entity registry for the QuickBooks Online source."""

from __future__ import annotations

import re
from dataclasses import dataclass

INTUIT_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

BASE_URLS = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}

# As of Aug 1, 2025 Intuit consolidated minor versions: 75 is the baseline and
# lower values are ignored.
MINOR_VERSION = "75"

# QBO query endpoint hard limit per page.
MAX_PAGE_SIZE = 1000

DEFAULT_INITIAL_TIMESTAMP = "2000-01-01T00:00:00Z"


@dataclass(frozen=True)
class EntityConfig:
    """Configuration for one queryable Accounting API entity.

    Attributes:
        name: The API entity name as used in the query dialect (e.g. "Invoice").
        incremental: Whether the entity supports filtering on
            Metadata.LastUpdatedTime (drives merge + incremental loading).
        cdc: Whether the entity is supported by the Change Data Capture endpoint.
        primary_key: Primary key column, or None for entities without a stable Id
            (loaded with write_disposition="replace").
    """

    name: str
    incremental: bool = True
    cdc: bool = True
    primary_key: str | None = "Id"


# All queryable Accounting API entities. CDC eligibility follows the entity list
# documented for the /cdc endpoint. Entities marked incremental=False are either
# singletons (CompanyInfo, Preferences), lack a usable LastUpdatedTime filter
# (ExchangeRate), or wrap other entities (RecurringTransaction).
ENTITIES: tuple[EntityConfig, ...] = (
    # -- name lists ---------------------------------------------------------
    EntityConfig("Account"),
    EntityConfig("Budget"),
    EntityConfig("Class"),
    EntityConfig("CompanyCurrency", cdc=False),
    EntityConfig("Customer"),
    EntityConfig("CustomerType", cdc=False),
    EntityConfig("Department"),
    EntityConfig("Employee"),
    EntityConfig("Item"),
    EntityConfig("PaymentMethod"),
    EntityConfig("TaxAgency", cdc=False),
    EntityConfig("TaxCode", cdc=False),
    EntityConfig("TaxRate", cdc=False),
    EntityConfig("Term", cdc=False),
    EntityConfig("Vendor"),
    # -- transactions -------------------------------------------------------
    EntityConfig("Bill"),
    EntityConfig("BillPayment"),
    EntityConfig("CreditCardPayment", cdc=False),
    EntityConfig("CreditMemo"),
    EntityConfig("Deposit"),
    EntityConfig("Estimate"),
    EntityConfig("Invoice"),
    EntityConfig("JournalEntry"),
    EntityConfig("Payment"),
    EntityConfig("Purchase"),
    EntityConfig("PurchaseOrder"),
    EntityConfig(
        "RecurringTransaction", incremental=False, cdc=False, primary_key=None
    ),
    EntityConfig("RefundReceipt"),
    EntityConfig("SalesReceipt"),
    EntityConfig("TimeActivity"),
    EntityConfig("Transfer"),
    EntityConfig("VendorCredit"),
    # -- supporting ---------------------------------------------------------
    EntityConfig("Attachable", cdc=False),
    EntityConfig("CompanyInfo", incremental=False, cdc=False),
    EntityConfig("ExchangeRate", incremental=False, cdc=False, primary_key=None),
    EntityConfig("Preferences", incremental=False),
)


# Reports API endpoints (GET /v3/company/{realmId}/reports/<name>). All accept
# optional query params (date ranges, accounting_method, summarize_column_by,
# …) and default to a sensible current period when called without params.
# Responses are capped at 400,000 cells — window large reports by date.
REPORTS: tuple[str, ...] = (
    "AccountList",
    "AgedPayableDetail",
    "AgedPayables",
    "AgedReceivableDetail",
    "AgedReceivables",
    "BalanceSheet",
    "CashFlow",
    "ClassSales",
    "CustomerBalance",
    "CustomerBalanceDetail",
    "CustomerIncome",
    "CustomerSales",
    "DepartmentSales",
    "GeneralLedger",
    "InventoryValuationDetail",
    "InventoryValuationSummary",
    "ItemSales",
    "JournalReport",
    "ProfitAndLoss",
    "ProfitAndLossDetail",
    "TaxSummary",
    "TransactionList",
    "TransactionListByCustomer",
    "TransactionListByVendor",
    "TrialBalance",
    "VendorBalance",
    "VendorBalanceDetail",
    "VendorExpenses",
)


def to_snake_case(entity_name: str) -> str:
    """Convert an API entity name to a snake_case resource/table name."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", entity_name).lower()
