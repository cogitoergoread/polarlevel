"""Configuration helpers for auth and environment inputs."""

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import AuthenticationError


REQUIRED_OAUTH_ENV_VARS = (
    "POLAR_USER_ID",
    "POLAR_CLIENT_ID",
    "POLAR_CLIENT_SECRET",
    "POLAR_REDIRECT_URI",
)

DEFAULT_ACCESSLINK_BASE_URL = "https://www.polaraccesslink.com"
DEFAULT_OAUTH_TOKEN_URL = "https://polarremote.com/v2/oauth2/token"
DEFAULT_TOKEN_STORE_PATH = ".secrets/polar_tokens.json"
DEFAULT_HTTP_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_COUNT = 3


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth credentials and token material loaded from environment."""

    user_id: str
    client_id: str
    client_secret: str
    redirect_uri: str
    access_token: str | None
    refresh_token: str | None
    accesslink_base_url: str
    token_endpoint_url: str
    token_store_path: Path
    http_timeout_seconds: int
    retry_count: int


def load_oauth_config_from_env() -> OAuthConfig:
    """Load OAuth settings from env vars or raise AuthenticationError."""

    values: dict[str, str] = {}
    missing: list[str] = []

    for key in REQUIRED_OAUTH_ENV_VARS:
        value = os.getenv(key)
        if value:
            values[key] = value
        else:
            missing.append(key)

    if missing:
        missing_csv = ", ".join(missing)
        raise AuthenticationError(
            f"Missing required OAuth environment variables: {missing_csv}"
        )

    timeout_raw = os.getenv("POLAR_ACCESSLINK_TIMEOUT_SECONDS", str(DEFAULT_HTTP_TIMEOUT_SECONDS))
    retry_raw = os.getenv("POLAR_ACCESSLINK_RETRY_COUNT", str(DEFAULT_RETRY_COUNT))

    try:
        timeout_seconds = int(timeout_raw)
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
    except ValueError as exc:
        raise AuthenticationError(
            "POLAR_ACCESSLINK_TIMEOUT_SECONDS must be a positive integer"
        ) from exc

    try:
        retry_count = int(retry_raw)
        if retry_count < 0:
            raise ValueError("retry_count must be non-negative")
    except ValueError as exc:
        raise AuthenticationError(
            "POLAR_ACCESSLINK_RETRY_COUNT must be a non-negative integer"
        ) from exc

    accesslink_base_url = os.getenv("POLAR_ACCESSLINK_BASE_URL", DEFAULT_ACCESSLINK_BASE_URL)
    accesslink_base_url = accesslink_base_url.rstrip("/")
    token_endpoint_url = os.getenv("POLAR_OAUTH_TOKEN_URL", DEFAULT_OAUTH_TOKEN_URL).rstrip("/")
    token_store_path = Path(
        os.getenv("POLAR_TOKEN_STORE_PATH", DEFAULT_TOKEN_STORE_PATH)
    ).expanduser()

    access_token = os.getenv("POLAR_ACCESS_TOKEN")
    refresh_token = os.getenv("POLAR_REFRESH_TOKEN")

    if (not access_token or not refresh_token) and not token_store_path.exists():
        raise AuthenticationError(
            "Provide POLAR_ACCESS_TOKEN and POLAR_REFRESH_TOKEN or configure "
            f"POLAR_TOKEN_STORE_PATH with a token file (current path: '{token_store_path}')"
        )

    return OAuthConfig(
        user_id=values["POLAR_USER_ID"],
        client_id=values["POLAR_CLIENT_ID"],
        client_secret=values["POLAR_CLIENT_SECRET"],
        redirect_uri=values["POLAR_REDIRECT_URI"],
        access_token=access_token,
        refresh_token=refresh_token,
        accesslink_base_url=accesslink_base_url,
        token_endpoint_url=token_endpoint_url,
        token_store_path=token_store_path,
        http_timeout_seconds=timeout_seconds,
        retry_count=retry_count,
    )
