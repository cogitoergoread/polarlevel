"""OAuth token state loading, refresh, and persistence."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .config import OAuthConfig
from .errors import AuthenticationError


@dataclass(frozen=True)
class TokenState:
    """Current OAuth token values used for API calls."""

    access_token: str
    refresh_token: str


def load_token_state(oauth_config: OAuthConfig) -> TokenState:
    """Load token values from token store and environment.

    Stored tokens take precedence so refreshed values are reused automatically.
    """

    stored = _read_token_store(oauth_config.token_store_path)

    access_token = _resolve_token_value(
        stored_value=stored.get("access_token"),
        env_value=oauth_config.access_token,
    )
    refresh_token = _resolve_token_value(
        stored_value=stored.get("refresh_token"),
        env_value=oauth_config.refresh_token,
    )

    if not access_token or not refresh_token:
        raise AuthenticationError(
            "OAuth tokens are missing. Set POLAR_ACCESS_TOKEN and POLAR_REFRESH_TOKEN "
            "or provide a valid token store file with access_token and refresh_token."
        )

    return TokenState(access_token=access_token, refresh_token=refresh_token)


def refresh_access_token(
    session: Any,
    oauth_config: OAuthConfig,
    refresh_token: str,
) -> TokenState:
    """Refresh OAuth access token using refresh token grant and persist new values."""

    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": oauth_config.client_id,
        "client_secret": oauth_config.client_secret,
    }

    try:
        response = session.request(
            method="POST",
            url=oauth_config.token_endpoint_url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=form,
            timeout=oauth_config.http_timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - HTTP client dependent
        raise AuthenticationError(f"Token refresh request failed: {exc}") from exc

    status_code = int(getattr(response, "status_code", 0))
    if status_code != 200:
        raise AuthenticationError(
            "Token refresh failed with HTTP "
            f"{status_code}. Body: {_safe_response_text(response)}"
        )

    payload = _parse_json_payload(response, context="token refresh")
    if not isinstance(payload, dict):
        raise AuthenticationError("Token refresh response must be a JSON object")

    new_access_token = payload.get("access_token")
    if not isinstance(new_access_token, str) or not new_access_token:
        raise AuthenticationError("Token refresh response missing access_token")

    new_refresh_token = payload.get("refresh_token")
    if not isinstance(new_refresh_token, str) or not new_refresh_token:
        new_refresh_token = refresh_token

    token_state = TokenState(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )
    persist_token_state(oauth_config.token_store_path, token_state)
    return token_state


def persist_token_state(path: Path, token_state: TokenState) -> None:
    """Persist token state to disk as JSON."""

    payload = {
        "access_token": token_state.access_token,
        "refresh_token": token_state.refresh_token,
        "updated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        tmp_path.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            # Some filesystems do not support chmod in a meaningful way.
            pass
    except OSError as exc:
        raise AuthenticationError(
            f"Failed to persist OAuth token state to '{path}': {exc}"
        ) from exc


def _read_token_store(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthenticationError(f"Failed reading token store file '{path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise AuthenticationError(f"Token store '{path}' must contain a JSON object")

    tokens: dict[str, str] = {}
    for key in ("access_token", "refresh_token"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            tokens[key] = value
    return tokens


def _resolve_token_value(stored_value: str | None, env_value: str | None) -> str | None:
    if stored_value:
        return stored_value
    if env_value:
        return env_value
    return None


def _parse_json_payload(response: Any, context: str) -> Any:
    try:
        return response.json()
    except Exception as exc:
        raise AuthenticationError(
            f"Invalid JSON in {context} response. Body: {_safe_response_text(response)}"
        ) from exc


def _safe_response_text(response: Any, max_length: int = 500) -> str:
    text = str(getattr(response, "text", ""))
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."
