"""OAuth token state tests."""

import json
from pathlib import Path
from typing import Any

import pytest

from polarlevel.config import OAuthConfig
from polarlevel.errors import AuthenticationError
from polarlevel.oauth import load_token_state, refresh_access_token


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                **kwargs,
            }
        )
        if not self._responses:
            raise AssertionError("No fake response configured for request")
        return self._responses.pop(0)


def make_oauth_config(
    tmp_path: Path,
    access_token: str | None = "env-access",
    refresh_token: str | None = "env-refresh",
) -> OAuthConfig:
    return OAuthConfig(
        user_id="123",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8000/callback",
        access_token=access_token,
        refresh_token=refresh_token,
        accesslink_base_url="https://polar.example.test",
        token_endpoint_url="https://polar.example.test/oauth/token",
        token_store_path=tmp_path / "tokens.json",
        http_timeout_seconds=10,
        retry_count=0,
    )


def test_load_token_state_prefers_store_values(tmp_path: Path) -> None:
    config = make_oauth_config(tmp_path)
    config.token_store_path.write_text(
        json.dumps(
            {
                "access_token": "file-access",
                "refresh_token": "file-refresh",
            }
        ),
        encoding="utf-8",
    )

    state = load_token_state(config)

    assert state.access_token == "file-access"
    assert state.refresh_token == "file-refresh"


def test_load_token_state_uses_environment_values_when_store_missing(tmp_path: Path) -> None:
    config = make_oauth_config(tmp_path, access_token="env-a", refresh_token="env-r")

    state = load_token_state(config)

    assert state.access_token == "env-a"
    assert state.refresh_token == "env-r"


def test_load_token_state_errors_when_no_tokens_available(tmp_path: Path) -> None:
    config = make_oauth_config(tmp_path, access_token=None, refresh_token=None)

    with pytest.raises(AuthenticationError, match="OAuth tokens are missing"):
        load_token_state(config)


def test_refresh_access_token_persists_new_tokens(tmp_path: Path) -> None:
    config = make_oauth_config(tmp_path)
    session = FakeSession(
        responses=[
            FakeResponse(
                200,
                {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                },
            )
        ]
    )

    state = refresh_access_token(session, config, refresh_token="old-refresh")

    assert state.access_token == "new-access"
    assert state.refresh_token == "new-refresh"
    persisted = json.loads(config.token_store_path.read_text(encoding="utf-8"))
    assert persisted["access_token"] == "new-access"
    assert persisted["refresh_token"] == "new-refresh"
    assert session.calls[0]["url"] == config.token_endpoint_url
    assert session.calls[0]["data"]["grant_type"] == "refresh_token"
    assert session.calls[0]["data"]["refresh_token"] == "old-refresh"


def test_refresh_access_token_keeps_existing_refresh_token_if_not_returned(
    tmp_path: Path,
) -> None:
    config = make_oauth_config(tmp_path)
    session = FakeSession(
        responses=[
            FakeResponse(
                200,
                {
                    "access_token": "new-access",
                },
            )
        ]
    )

    state = refresh_access_token(session, config, refresh_token="old-refresh")

    assert state.access_token == "new-access"
    assert state.refresh_token == "old-refresh"
