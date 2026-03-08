"""OAuth token state loading, refresh, and persistence."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .config import OAuthConfig
from .errors import AuthenticationError


@dataclass(frozen=True)
class TokenState:
    """Current OAuth token values used for API calls."""

    access_token: str
    refresh_token: str
    access_token_expires_at_utc: datetime | None = None


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
    access_token_expires_at_utc = _resolve_token_expiry(
        stored_value=stored.get("access_token_expires_at_utc"),
        env_value=oauth_config.access_token_expires_at_utc,
    )

    if not access_token or not refresh_token:
        raise AuthenticationError(
            "OAuth tokens are missing. Set POLAR_ACCESS_TOKEN and POLAR_REFRESH_TOKEN "
            "or provide a valid token store file with access_token and refresh_token."
        )

    return TokenState(
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_at_utc=access_token_expires_at_utc,
    )


def is_token_expiring_soon(
    token_state: TokenState,
    safety_window_seconds: int,
) -> bool:
    """Return True when token expiry is known and inside safety window."""

    if token_state.access_token_expires_at_utc is None:
        return False

    now_utc = datetime.now(timezone.utc)
    threshold = now_utc + timedelta(seconds=safety_window_seconds)
    return token_state.access_token_expires_at_utc <= threshold


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

    access_token_expires_at_utc = _extract_access_token_expiry(payload)

    token_state = TokenState(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        access_token_expires_at_utc=access_token_expires_at_utc,
    )
    persist_token_state(oauth_config.token_store_path, token_state)
    return token_state


def persist_token_state(path: Path, token_state: TokenState) -> None:
    """Persist token state to disk as JSON."""

    updated_at_utc = datetime.now(timezone.utc).replace(microsecond=0)
    payload: dict[str, Any] = {
        "access_token": token_state.access_token,
        "refresh_token": token_state.refresh_token,
        "updated_at_utc": updated_at_utc.isoformat().replace("+00:00", "Z"),
    }
    if token_state.access_token_expires_at_utc is not None:
        payload["access_token_expires_at_utc"] = (
            token_state.access_token_expires_at_utc.replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

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


def _read_token_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthenticationError(f"Failed reading token store file '{path}': {exc}") from exc

    if not isinstance(payload, dict):
        raise AuthenticationError(f"Token store '{path}' must contain a JSON object")

    return payload


def _resolve_token_value(stored_value: Any, env_value: str | None) -> str | None:
    if stored_value:
        if isinstance(stored_value, str):
            return stored_value
        raise AuthenticationError("Token store access_token/refresh_token values must be strings")
    if env_value:
        return env_value
    return None


def _resolve_token_expiry(stored_value: Any, env_value: str | None) -> datetime | None:
    if stored_value not in (None, ""):
        return _parse_utc_datetime(
            stored_value,
            field_label="token store access_token_expires_at_utc",
        )
    if env_value not in (None, ""):
        return _parse_utc_datetime(
            env_value,
            field_label="POLAR_ACCESS_TOKEN_EXPIRES_AT_UTC",
        )
    return None


def _extract_access_token_expiry(payload: Mapping[str, Any]) -> datetime | None:
    direct_value = _first_non_empty(
        payload,
        "access_token_expires_at_utc",
        "accessTokenExpiresAtUtc",
        "expires_at",
        "expiresAt",
    )
    if direct_value is not None:
        return _parse_utc_datetime(direct_value, field_label="token refresh expiry")

    expires_in_raw = _first_non_empty(payload, "expires_in", "expiresIn")
    if expires_in_raw is None:
        return None

    expires_in_seconds = _to_int(expires_in_raw)
    if expires_in_seconds is None or expires_in_seconds <= 0:
        raise AuthenticationError("Token refresh response has invalid expires_in value")

    return datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)


def _parse_utc_datetime(value: Any, field_label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AuthenticationError(f"{field_label} must be a non-empty ISO-8601 timestamp")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthenticationError(
            f"{field_label} must be an ISO-8601 timestamp, got: '{value}'"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _first_non_empty(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
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
