"""Configuration helpers for auth and environment inputs."""

import os
from dataclasses import dataclass

from .errors import AuthenticationError


REQUIRED_OAUTH_ENV_VARS = (
    "POLAR_CLIENT_ID",
    "POLAR_CLIENT_SECRET",
    "POLAR_REDIRECT_URI",
    "POLAR_ACCESS_TOKEN",
    "POLAR_REFRESH_TOKEN",
)


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth credentials and token material loaded from environment."""

    client_id: str
    client_secret: str
    redirect_uri: str
    access_token: str
    refresh_token: str


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

    return OAuthConfig(
        client_id=values["POLAR_CLIENT_ID"],
        client_secret=values["POLAR_CLIENT_SECRET"],
        redirect_uri=values["POLAR_REDIRECT_URI"],
        access_token=values["POLAR_ACCESS_TOKEN"],
        refresh_token=values["POLAR_REFRESH_TOKEN"],
    )
