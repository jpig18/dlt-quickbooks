"""Paginator for the QuickBooks Online query endpoint.

QBO paginates with ``STARTPOSITION``/``MAXRESULTS`` clauses embedded in the
SQL-like ``query`` request parameter (not as standalone request params), so
none of dlt's built-in paginators apply.
"""

from __future__ import annotations

from typing import Any

from dlt.sources.helpers.rest_client.paginators import BasePaginator
from requests import Request, Response

from ..settings import MAX_PAGE_SIZE


class QboQueryPaginator(BasePaginator):
    """Appends ``STARTPOSITION {n} MAXRESULTS {page_size}`` to the query param.

    STARTPOSITION is 1-based; a page smaller than ``page_size`` signals the
    last page. The same ``Request`` object is mutated across pages, so the
    original query is captured once and the clause is rewritten (never
    stacked) on each page.
    """

    def __init__(self, page_size: int = MAX_PAGE_SIZE) -> None:
        super().__init__()
        self.page_size = page_size
        self._start_position = 1
        self._base_query: str | None = None

    def init_request(self, request: Request) -> None:
        self._start_position = 1
        self._base_query = None
        self.update_request(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if data is None or len(data) < self.page_size:
            self._has_next_page = False
        else:
            self._start_position += self.page_size

    def update_request(self, request: Request) -> None:
        params: dict[str, Any] = request.params if request.params is not None else {}
        if self._base_query is None:
            self._base_query = str(params.get("query", ""))
        params["query"] = (
            f"{self._base_query} STARTPOSITION {self._start_position} MAXRESULTS {self.page_size}"
        )
        request.params = params
