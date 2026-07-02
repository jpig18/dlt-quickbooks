import json
from pathlib import Path
from typing import Any

import pytest
import requests
from requests import Request

from quickbooks.helpers.auth import FileTokenStore, QboRefreshTokenAuth
from quickbooks.settings import INTUIT_TOKEN_URL


def make_auth(tmp_path: Path, **kwargs: Any) -> QboRefreshTokenAuth:
    return QboRefreshTokenAuth(
        client_id="test-client",
        client_secret="test-secret",
        refresh_token="initial-token",
        token_store=FileTokenStore(tmp_path / "token.json"),
        session=requests.Session(),
        **kwargs,
    )


def token_response(refresh_token: str = "rotated-token") -> dict[str, Any]:
    return {
        "access_token": "access-123",
        "refresh_token": refresh_token,
        "expires_in": 3600,
        "token_type": "bearer",
    }


def test_attaches_bearer_token(requests_mock: Any, tmp_path: Path) -> None:
    requests_mock.post(INTUIT_TOKEN_URL, json=token_response())
    auth = make_auth(tmp_path)

    request = auth(Request("GET", "https://example.com").prepare())

    assert request.headers["Authorization"] == "Bearer access-123"


def test_token_request_uses_refresh_grant_and_basic_auth(
    requests_mock: Any, tmp_path: Path
) -> None:
    requests_mock.post(INTUIT_TOKEN_URL, json=token_response())
    auth = make_auth(tmp_path)

    auth.obtain_token()

    token_request = requests_mock.request_history[0]
    assert "grant_type=refresh_token" in token_request.text
    assert "refresh_token=initial-token" in token_request.text
    assert token_request.headers["Authorization"].startswith("Basic ")


def test_rotated_refresh_token_is_persisted(requests_mock: Any, tmp_path: Path) -> None:
    requests_mock.post(INTUIT_TOKEN_URL, json=token_response("rotated-token"))
    auth = make_auth(tmp_path)

    auth.obtain_token()

    assert auth.refresh_token == "rotated-token"
    stored = json.loads((tmp_path / "token.json").read_text())
    assert stored["refresh_token"] == "rotated-token"

    # the next refresh must use the rotated token
    auth.obtain_token()
    assert "refresh_token=rotated-token" in requests_mock.request_history[-1].text


def test_stored_token_supersedes_configured_token(
    requests_mock: Any, tmp_path: Path
) -> None:
    FileTokenStore(tmp_path / "token.json").save("previously-rotated")
    requests_mock.post(INTUIT_TOKEN_URL, json=token_response())
    auth = make_auth(tmp_path)

    assert auth.refresh_token == "previously-rotated"
    auth.obtain_token()
    assert "refresh_token=previously-rotated" in requests_mock.request_history[0].text


def test_token_refresh_http_error_raises(requests_mock: Any, tmp_path: Path) -> None:
    requests_mock.post(
        INTUIT_TOKEN_URL, status_code=400, json={"error": "invalid_grant"}
    )
    auth = make_auth(tmp_path)

    with pytest.raises(requests.HTTPError):
        auth.obtain_token()


def test_file_token_store_roundtrip(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path / "nested" / "token.json")
    assert store.load() is None
    store.save("abc")
    assert store.load() == "abc"
