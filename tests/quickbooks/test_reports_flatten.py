from typing import Any

from quickbooks.helpers.reports import flatten_report

# Representative ProfitAndLoss response: nested sections, data rows, summary
# rows, an unnamed first column, and entity ids on cells.
PNL_PAYLOAD: dict[str, Any] = {
    "Header": {
        "ReportName": "ProfitAndLoss",
        "StartPeriod": "2026-01-01",
        "EndPeriod": "2026-06-30",
        "Currency": "USD",
        "ReportBasis": "Accrual",
        "Time": "2026-07-02T10:00:00-07:00",
    },
    "Columns": {
        "Column": [
            {"ColTitle": "", "ColType": "Account"},
            {"ColTitle": "Total", "ColType": "Money"},
        ]
    },
    "Rows": {
        "Row": [
            {
                "type": "Section",
                "group": "Income",
                "Header": {"ColData": [{"value": "Income"}, {"value": ""}]},
                "Rows": {
                    "Row": [
                        {
                            "type": "Data",
                            "ColData": [
                                {"value": "Design income", "id": "82"},
                                {"value": "975.00"},
                            ],
                        },
                        {
                            "type": "Section",
                            "Header": {
                                "ColData": [{"value": "Landscaping"}, {"value": ""}]
                            },
                            "Rows": {
                                "Row": [
                                    {
                                        "type": "Data",
                                        "ColData": [
                                            {"value": "Labor", "id": "90"},
                                            {"value": "50.00"},
                                        ],
                                    }
                                ]
                            },
                            "Summary": {
                                "ColData": [
                                    {"value": "Total Landscaping"},
                                    {"value": "50.00"},
                                ]
                            },
                        },
                    ]
                },
                "Summary": {
                    "ColData": [{"value": "Total Income"}, {"value": "1025.00"}]
                },
            },
            {
                "type": "Data",
                "ColData": [{"value": "Net Income"}, {"value": "1025.00"}],
            },
        ]
    },
}


def test_flatten_report_metadata_on_every_row() -> None:
    rows = list(flatten_report(PNL_PAYLOAD))
    assert rows
    for row in rows:
        assert row["report_name"] == "ProfitAndLoss"
        assert row["start_period"] == "2026-01-01"
        assert row["end_period"] == "2026-06-30"
        assert row["currency"] == "USD"
        assert row["report_basis"] == "Accrual"


def test_flatten_report_columns_and_ids() -> None:
    rows = list(flatten_report(PNL_PAYLOAD))
    design = next(r for r in rows if r.get("account") == "Design income")
    assert design["total"] == "975.00"
    assert design["account_id"] == "82"
    assert design["row_type"] == "Data"
    assert design["section_path"] == "Income"


def test_flatten_report_nested_sections_and_summaries() -> None:
    rows = list(flatten_report(PNL_PAYLOAD))
    labor = next(r for r in rows if r.get("account") == "Labor")
    assert labor["section_path"] == "Income > Landscaping"

    landscaping_total = next(r for r in rows if r.get("account") == "Total Landscaping")
    assert landscaping_total["row_type"] == "Summary"
    assert landscaping_total["total"] == "50.00"

    income_total = next(r for r in rows if r.get("account") == "Total Income")
    assert income_total["section_path"] == "Income"
    assert income_total["total"] == "1025.00"


def test_flatten_report_top_level_data_row() -> None:
    rows = list(flatten_report(PNL_PAYLOAD))
    net = next(r for r in rows if r.get("account") == "Net Income")
    assert net["section_path"] is None
    assert net["total"] == "1025.00"


def test_flatten_report_empty_report() -> None:
    payload = {
        "Header": {"ReportName": "CashFlow", "Time": "2026-07-02T10:00:00-07:00"},
        "Columns": {"Column": []},
        "Rows": {},
    }
    assert list(flatten_report(payload)) == []


def test_flatten_report_duplicate_column_titles() -> None:
    payload = {
        "Header": {"ReportName": "X"},
        "Columns": {
            "Column": [
                {"ColTitle": "Total", "ColType": "Money"},
                {"ColTitle": "Total", "ColType": "Money"},
            ]
        },
        "Rows": {
            "Row": [{"type": "Data", "ColData": [{"value": "1"}, {"value": "2"}]}]
        },
    }
    (row,) = list(flatten_report(payload))
    assert row["total"] == "1"
    assert row["total_1"] == "2"
