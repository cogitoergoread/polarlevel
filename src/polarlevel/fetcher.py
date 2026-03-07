"""Data retrieval layer for Polar API integration."""

from collections.abc import Mapping
from datetime import datetime, timezone
import time
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - depends on local environment
    requests = None  # type: ignore[assignment]

from .config import OAuthConfig
from .errors import ApiError, AuthenticationError
from .models import FetchRequest, TelemetryRecord
from .oauth import TokenState, load_token_state, refresh_access_token

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def _dry_run_sample() -> list[TelemetryRecord]:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    return [
        TelemetryRecord(
            user_id="dry-run-user",
            session_id="dry-run-session",
            timestamp_utc=now_utc.isoformat().replace("+00:00", "Z"),
            heart_rate_bpm=120,
            latitude=47.4979,
            longitude=19.0402,
            elevation_m=96.0,
        )
    ]


def _build_session() -> Any:
    if requests is None:
        raise ApiError(
            "The 'requests' package is required for live Polar AccessLink calls. "
            "Install project dependencies and try again."
        )
    return requests.Session()


def fetch_records(
    request: FetchRequest,
    oauth_config: OAuthConfig | None,
    session: Any | None = None,
) -> list[TelemetryRecord]:
    """Fetch records for a request.

    When `dry_run` is true, returns a deterministic sample record.
    Otherwise, performs the Polar AccessLink exercise transaction flow:
    create transaction -> list resources -> download exercises -> commit transaction.
    """

    if request.dry_run:
        return _dry_run_sample()

    if oauth_config is None:
        raise ApiError("OAuth configuration is required for live AccessLink calls")

    http = session or _build_session()
    token_context: dict[str, TokenState] = {"state": load_token_state(oauth_config)}
    headers = {"Accept": "application/json"}
    base_url = oauth_config.accesslink_base_url.rstrip("/")

    transaction_id = _create_exercise_transaction(
        http,
        oauth_config,
        base_url,
        headers,
        token_context,
    )

    exercise_refs = _list_exercises_from_transaction(
        http,
        oauth_config,
        base_url,
        headers,
        token_context,
        transaction_id,
    )

    all_records: list[TelemetryRecord] = []
    for exercise_ref in exercise_refs:
        detail_payload = _fetch_exercise_detail(
            http,
            oauth_config,
            base_url,
            headers,
            token_context,
            exercise_ref,
        )
        all_records.extend(_normalize_exercise_payload(detail_payload, oauth_config.user_id))

    _commit_exercise_transaction(
        http,
        oauth_config,
        base_url,
        headers,
        token_context,
        transaction_id,
    )

    return _apply_request_scope(all_records, request)


def _create_exercise_transaction(
    session: Any,
    oauth_config: OAuthConfig,
    base_url: str,
    headers: Mapping[str, str],
    token_context: dict[str, TokenState],
) -> str:
    endpoint = f"{base_url}/v3/users/{oauth_config.user_id}/exercise-transactions"
    payload = _request_json(
        session=session,
        oauth_config=oauth_config,
        method="POST",
        url=endpoint,
        headers=headers,
        token_context=token_context,
        expected_statuses={200, 201},
        context="creating exercise transaction",
    )
    transaction_id = _first_non_empty(
        payload,
        "transaction-id",
        "transactionId",
        "id",
    )
    if transaction_id is None:
        raise ApiError("Exercise transaction response did not include a transaction id")
    return str(transaction_id)


def _list_exercises_from_transaction(
    session: Any,
    oauth_config: OAuthConfig,
    base_url: str,
    headers: Mapping[str, str],
    token_context: dict[str, TokenState],
    transaction_id: str,
) -> list[dict[str, Any]]:
    endpoint = f"{base_url}/v3/exercise-transactions/{transaction_id}"
    payload = _request_json(
        session=session,
        oauth_config=oauth_config,
        method="GET",
        url=endpoint,
        headers=headers,
        token_context=token_context,
        expected_statuses={200},
        context="listing exercise resources from transaction",
    )

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        raw_items = payload.get("exercises") or payload.get("items") or payload.get("resources")
        if isinstance(raw_items, list):
            return [item for item in raw_items if isinstance(item, dict)]

    raise ApiError("Unexpected exercise transaction list payload format")


def _fetch_exercise_detail(
    session: Any,
    oauth_config: OAuthConfig,
    base_url: str,
    headers: Mapping[str, str],
    token_context: dict[str, TokenState],
    exercise_ref: Mapping[str, Any],
) -> dict[str, Any]:
    detail_url = _resolve_exercise_url(base_url, exercise_ref)
    payload = _request_json(
        session=session,
        oauth_config=oauth_config,
        method="GET",
        url=detail_url,
        headers=headers,
        token_context=token_context,
        expected_statuses={200},
        context="downloading exercise detail",
    )
    if not isinstance(payload, dict):
        raise ApiError("Unexpected exercise detail payload format")
    return payload


def _commit_exercise_transaction(
    session: Any,
    oauth_config: OAuthConfig,
    base_url: str,
    headers: Mapping[str, str],
    token_context: dict[str, TokenState],
    transaction_id: str,
) -> None:
    endpoint = f"{base_url}/v3/exercise-transactions/{transaction_id}"
    _request_json(
        session=session,
        oauth_config=oauth_config,
        method="PUT",
        url=endpoint,
        headers=headers,
        token_context=token_context,
        expected_statuses={200, 204},
        context="committing exercise transaction",
    )


def _resolve_exercise_url(base_url: str, exercise_ref: Mapping[str, Any]) -> str:
    url_value = _first_non_empty(exercise_ref, "url")
    if isinstance(url_value, str) and url_value:
        if url_value.startswith("http://") or url_value.startswith("https://"):
            return url_value
        return f"{base_url}/{url_value.lstrip('/')}"

    exercise_id = _first_non_empty(exercise_ref, "id", "exercise-id", "exerciseId")
    if exercise_id is None:
        raise ApiError("Exercise reference did not include a usable id or url")
    return f"{base_url}/v3/exercises/{exercise_id}"


def _request_json(
    session: Any,
    oauth_config: OAuthConfig,
    method: str,
    url: str,
    headers: Mapping[str, str],
    token_context: dict[str, TokenState],
    expected_statuses: set[int],
    context: str,
) -> Any:
    attempt = 0
    did_refresh = False
    last_exception: Exception | None = None

    while attempt <= oauth_config.retry_count:
        request_headers = dict(headers)
        request_headers["Authorization"] = f"Bearer {token_context['state'].access_token}"

        try:
            response = session.request(
                method=method,
                url=url,
                headers=request_headers,
                timeout=oauth_config.http_timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - network lib dependent
            last_exception = exc
            if attempt >= oauth_config.retry_count:
                break
            _sleep_before_retry(attempt)
            attempt += 1
            continue

        status_code = int(getattr(response, "status_code", 0))
        if status_code in expected_statuses:
            if status_code == 204:
                return {}
            return _decode_json_response(response, context)

        if status_code == 401:
            if did_refresh:
                raise AuthenticationError(
                    "Request remained unauthorized after OAuth token refresh"
                )
            token_context["state"] = refresh_access_token(
                session=session,
                oauth_config=oauth_config,
                refresh_token=token_context["state"].refresh_token,
            )
            did_refresh = True
            continue

        if status_code in TRANSIENT_STATUS_CODES and attempt < oauth_config.retry_count:
            _sleep_before_retry(attempt)
            attempt += 1
            continue

        body_text = _safe_response_text(response)
        raise ApiError(
            f"AccessLink request failed while {context}: "
            f"HTTP {status_code}. Body: {body_text}"
        )

    if last_exception is not None:
        raise ApiError(
            f"AccessLink request failed while {context}: {last_exception}"
        ) from last_exception

    raise ApiError(f"AccessLink request failed while {context}")


def _decode_json_response(response: Any, context: str) -> Any:
    try:
        return response.json()
    except Exception as exc:
        body_text = _safe_response_text(response)
        raise ApiError(
            f"Invalid JSON response while {context}. Body: {body_text}"
        ) from exc


def _safe_response_text(response: Any, max_length: int = 500) -> str:
    text = str(getattr(response, "text", ""))
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def _sleep_before_retry(attempt: int) -> None:
    delay_seconds = 0.5 * (2**attempt)
    time.sleep(delay_seconds)


def _normalize_exercise_payload(
    exercise: Mapping[str, Any],
    user_id: str,
) -> list[TelemetryRecord]:
    session_id_raw = _first_non_empty(exercise, "id", "exercise-id", "exerciseId")
    session_id = str(session_id_raw) if session_id_raw is not None else "unknown-session"

    samples_node = exercise.get("samples")
    heart_rate_samples = _extract_heart_rate_samples(samples_node)
    route_samples = _extract_route_samples(samples_node)

    if heart_rate_samples:
        return _records_from_heart_rate_samples(
            user_id=user_id,
            session_id=session_id,
            heart_rate_samples=heart_rate_samples,
            route_samples=route_samples,
        )

    fallback_timestamp = _normalize_timestamp(
        _first_non_empty(
            exercise,
            "start-time",
            "startTime",
            "date-time",
            "timestamp",
        )
    )
    fallback_hr = _to_int(_first_non_empty(exercise, "average-heart-rate", "averageHeartRate"))

    return [
        TelemetryRecord(
            user_id=user_id,
            session_id=session_id,
            timestamp_utc=fallback_timestamp,
            heart_rate_bpm=fallback_hr or 0,
            latitude=None,
            longitude=None,
            elevation_m=None,
        )
    ]


def _records_from_heart_rate_samples(
    user_id: str,
    session_id: str,
    heart_rate_samples: list[Mapping[str, Any]],
    route_samples: list[Mapping[str, Any]],
) -> list[TelemetryRecord]:
    route_by_time: dict[str, Mapping[str, Any]] = {}
    for route_sample in route_samples:
        route_time = _normalize_timestamp(
            _first_non_empty(route_sample, "date-time", "timestamp", "time")
        )
        route_by_time[route_time] = route_sample

    records: list[TelemetryRecord] = []
    for index, hr_sample in enumerate(heart_rate_samples):
        bpm = _to_int(_first_non_empty(hr_sample, "value", "heart-rate", "heartRate"))
        timestamp = _normalize_timestamp(
            _first_non_empty(hr_sample, "date-time", "timestamp", "time")
        )
        if bpm is None:
            continue

        route_sample = route_by_time.get(timestamp)
        if route_sample is None and index < len(route_samples):
            route_sample = route_samples[index]

        latitude, longitude, elevation = _extract_route_coordinates(route_sample)

        records.append(
            TelemetryRecord(
                user_id=user_id,
                session_id=session_id,
                timestamp_utc=timestamp,
                heart_rate_bpm=bpm,
                latitude=latitude,
                longitude=longitude,
                elevation_m=elevation,
            )
        )

    return records


def _extract_heart_rate_samples(samples_node: Any) -> list[Mapping[str, Any]]:
    if not isinstance(samples_node, dict):
        return []

    raw_values = (
        samples_node.get("heart-rate")
        or samples_node.get("heartRate")
        or samples_node.get("heart_rate")
    )
    if isinstance(raw_values, list):
        return [item for item in raw_values if isinstance(item, dict)]
    return []


def _extract_route_samples(samples_node: Any) -> list[Mapping[str, Any]]:
    if not isinstance(samples_node, dict):
        return []

    raw_values = (
        samples_node.get("recorded-route")
        or samples_node.get("recordedRoute")
        or samples_node.get("route")
    )
    if isinstance(raw_values, list):
        return [item for item in raw_values if isinstance(item, dict)]
    return []


def _extract_route_coordinates(
    route_sample: Mapping[str, Any] | None,
) -> tuple[float | None, float | None, float | None]:
    if route_sample is None:
        return None, None, None

    latitude = _to_float(_first_non_empty(route_sample, "latitude", "lat"))
    longitude = _to_float(_first_non_empty(route_sample, "longitude", "lon", "lng"))
    elevation = _to_float(_first_non_empty(route_sample, "altitude", "elevation", "alt"))
    return latitude, longitude, elevation


def _apply_request_scope(
    records: list[TelemetryRecord],
    request: FetchRequest,
) -> list[TelemetryRecord]:
    if request.latest:
        return records

    if request.start_date is None or request.end_date is None:
        return records

    filtered: list[TelemetryRecord] = []
    for record in records:
        timestamp = _parse_timestamp(record.timestamp_utc)
        day = timestamp.date()
        if request.start_date <= day <= request.end_date:
            filtered.append(record)
    return filtered


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_timestamp(raw_value: Any) -> str:
    if raw_value is None:
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        return now_utc.isoformat().replace("+00:00", "Z")

    parsed = _parse_timestamp(str(raw_value))
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first_non_empty(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
