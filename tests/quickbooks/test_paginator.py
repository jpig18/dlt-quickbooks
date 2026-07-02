from requests import Request, Response

from quickbooks.helpers.paginator import QboQueryPaginator

BASE_QUERY = "SELECT * FROM Invoice ORDERBY Metadata.LastUpdatedTime"


def make_request() -> Request:
    return Request("GET", "https://example.com/query", params={"query": BASE_QUERY})


def test_first_page_appends_clause() -> None:
    paginator = QboQueryPaginator(page_size=1000)
    request = make_request()
    paginator.init_request(request)
    assert request.params["query"] == f"{BASE_QUERY} STARTPOSITION 1 MAXRESULTS 1000"


def test_full_page_advances_without_stacking_clauses() -> None:
    paginator = QboQueryPaginator(page_size=2)
    request = make_request()
    paginator.init_request(request)

    paginator.update_state(Response(), data=[{"Id": "1"}, {"Id": "2"}])
    assert paginator.has_next_page
    paginator.update_request(request)
    assert request.params["query"] == f"{BASE_QUERY} STARTPOSITION 3 MAXRESULTS 2"

    paginator.update_state(Response(), data=[{"Id": "3"}, {"Id": "4"}])
    paginator.update_request(request)
    # the clause is rewritten in place, never appended twice
    assert request.params["query"] == f"{BASE_QUERY} STARTPOSITION 5 MAXRESULTS 2"
    assert request.params["query"].count("STARTPOSITION") == 1


def test_short_page_stops_pagination() -> None:
    paginator = QboQueryPaginator(page_size=1000)
    request = make_request()
    paginator.init_request(request)
    paginator.update_state(Response(), data=[{"Id": "1"}])
    assert not paginator.has_next_page


def test_empty_page_stops_pagination() -> None:
    paginator = QboQueryPaginator(page_size=1000)
    request = make_request()
    paginator.init_request(request)
    paginator.update_state(Response(), data=None)
    assert not paginator.has_next_page


def test_init_resets_state() -> None:
    paginator = QboQueryPaginator(page_size=2)
    request = make_request()
    paginator.init_request(request)
    paginator.update_state(Response(), data=[{"Id": "1"}, {"Id": "2"}])
    paginator.update_request(request)

    fresh_request = make_request()
    paginator.init_request(fresh_request)
    assert fresh_request.params["query"] == f"{BASE_QUERY} STARTPOSITION 1 MAXRESULTS 2"
