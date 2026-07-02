"""OAuth2 authentication for QuickBooks Online with rotating refresh-token persistence.

Intuit rotates the refresh token roughly every 24 hours: each token refresh
may return a NEW refresh token that must be used from then on. A static
credential (e.g. in ``secrets.toml``) therefore eventually goes stale. This
module persists rotated tokens through a pluggable :class:`TokenStore`.
"""

from __future__ import annotations

import json
from base64 import b64encode
from pathlib import Path
from typing import Annotated, Any, Protocol

import pendulum
from dlt.common.configuration.specs.base_configuration import NotResolved, configspec
from dlt.common.typing import TSecretStrValue
from dlt.sources.helpers.rest_client.auth import OAuth2ClientCredentials

from ..settings import INTUIT_TOKEN_URL


class TokenStore(Protocol):
    """Persistence for the rotating QuickBooks refresh token.

    Implement this against your secret manager for production schedules
    (e.g. AWS Secrets Manager, Vault). ``load`` returning ``None`` means no
    stored token yet; the initially configured token is used instead.
    """

    def load(self) -> str | None:
        """Return the most recently stored refresh token, if any."""
        ...

    def save(self, refresh_token: str) -> None:
        """Persist a newly rotated refresh token."""
        ...


class FileTokenStore:
    """Stores the rotated refresh token in a local JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text())
        token = payload.get("refresh_token")
        return str(token) if token else None

    def save(self, refresh_token: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "refresh_token": refresh_token,
                    "updated_at": pendulum.now().isoformat(),
                }
            )
        )


@configspec
class QboRefreshTokenAuth(OAuth2ClientCredentials):
    """OAuth2 refresh-token grant against Intuit's token endpoint.

    Exchanges the refresh token for a bearer access token (1h TTL, re-obtained
    automatically on expiry) and captures the rotated refresh token from every
    response, persisting it via ``token_store``.
    """

    access_token_url: str = INTUIT_TOKEN_URL
    # dlt configspec convention: required secret fields default to None
    refresh_token: TSecretStrValue = None  # type: ignore[assignment]
    token_store: Annotated[TokenStore | None, NotResolved()] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        # A previously rotated token in the store supersedes the configured one.
        if self.token_store is not None:
            stored = self.token_store.load()
            if stored:
                self.refresh_token = stored

    def build_access_token_request(self) -> dict[str, Any]:
        basic = b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        return {
            "headers": {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            "data": {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
        }

    def obtain_token(self) -> None:
        response = self.session.post(
            self.access_token_url, **self.build_access_token_request()
        )
        response.raise_for_status()
        response_json = response.json()
        self.parse_native_representation(self.parse_access_token(response_json))
        expires_in_seconds = self.parse_expiration_in_seconds(response_json)
        self.token_expiry = pendulum.now().add(seconds=expires_in_seconds)
        rotated = response_json.get("refresh_token")
        if rotated and rotated != self.refresh_token:
            self.refresh_token = rotated
            if self.token_store is not None:
                self.token_store.save(rotated)
