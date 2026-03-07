"""Configuration loading tests for OAuth settings."""

import json
from pathlib import Path

import pytest

from polarlevel.config import load_oauth_config_from_env
from polarlevel.errors import AuthenticationError


def _set_required_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POLAR_USER_ID", "123")
    monkeypatch.setenv("POLAR_CLIENT_ID", "client-id")
    monkeypatch.setenv("POLAR_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("POLAR_REDIRECT_URI", "http://localhost:8000/callback")


def _clear_optional_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "POLAR_ACCESS_TOKEN",
        "POLAR_REFRESH_TOKEN",
        "POLAR_ACCESSLINK_BASE_URL",
        "POLAR_OAUTH_TOKEN_URL",
        "POLAR_TOKEN_STORE_PATH",
        "POLAR_ACCESSLINK_TIMEOUT_SECONDS",
        "POLAR_ACCESSLINK_RETRY_COUNT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_oauth_config_accepts_token_store_without_env_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_base_env(monkeypatch)
    _clear_optional_env(monkeypatch)

    token_store = tmp_path / "tokens.json"
    token_store.write_text(
        json.dumps({"access_token": "file-access", "refresh_token": "file-refresh"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("POLAR_TOKEN_STORE_PATH", str(token_store))

    config = load_oauth_config_from_env()

    assert config.access_token is None
    assert config.refresh_token is None
    assert config.token_store_path == token_store


def test_load_oauth_config_requires_token_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_base_env(monkeypatch)
    _clear_optional_env(monkeypatch)

    missing_store = tmp_path / "missing-tokens.json"
    monkeypatch.setenv("POLAR_TOKEN_STORE_PATH", str(missing_store))

    with pytest.raises(AuthenticationError, match="Provide POLAR_ACCESS_TOKEN"):
        load_oauth_config_from_env()


def test_load_oauth_config_uses_env_tokens_when_store_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_base_env(monkeypatch)
    _clear_optional_env(monkeypatch)

    missing_store = tmp_path / "missing-tokens.json"
    monkeypatch.setenv("POLAR_TOKEN_STORE_PATH", str(missing_store))
    monkeypatch.setenv("POLAR_ACCESS_TOKEN", "env-access")
    monkeypatch.setenv("POLAR_REFRESH_TOKEN", "env-refresh")

    config = load_oauth_config_from_env()

    assert config.access_token == "env-access"
    assert config.refresh_token == "env-refresh"
    assert config.token_store_path == missing_store
