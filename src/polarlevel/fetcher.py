"""Data retrieval layer for Polar API integration."""

from collections.abc import Callable, Mapping
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
from .oauth import (
    TokenState,
    is_token_expiring_soon,
    load_token_state,
    refresh_access_token,
)

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
PROACTIVE_REFRESH_SAFETY_WINDOW_SECONDS = 60


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

    _refresh_token_if_expiring(http, oauth_config, token_context)

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


def _refresh_token_if_expiring(
    session: Any,
    oauth_config: OAuthConfig,
    token_context: dict[str, TokenState],
) -> None:
    if not is_token_expiring_soon(
        token_context["state"],
        safety_window_seconds=PROACTIVE_REFRESH_SAFETY_WINDOW_SECONDS,
    ):
        return

    token_context["state"] = refresh_access_token(
        session=session,
        oauth_config=oauth_config,
        refresh_token=token_context["state"].refresh_token,
    )


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

    samples_node = _resolve_samples_node(exercise)
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
            "start_time",
            "startTimeUtc",
            "date-time",
            "timestamp",
        )
    )
    fallback_hr = _to_int(
        _first_non_empty(
            exercise,
            "average-heart-rate",
            "averageHeartRate",
            "avg-heart-rate",
            "avgHeartRate",
            "heart-rate-average",
            "heartRateAverage",
        )
    )

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
            _first_non_empty(
                route_sample,
                "date-time",
                "dateTime",
                "timestamp",
                "time",
                "timeStamp",
                "utc",
            )
        )
        route_by_time[route_time] = route_sample

    records: list[TelemetryRecord] = []
    for index, hr_sample in enumerate(heart_rate_samples):
        bpm = _to_int(
            _first_non_empty(
                hr_sample,
                "value",
                "heart-rate",
                "heartRate",
                "heart_rate",
                "hr",
                "bpm",
                "beats-per-minute",
                "beatsPerMinute",
            )
        )
        timestamp = _normalize_timestamp(
            _first_non_empty(
                hr_sample,
                "date-time",
                "dateTime",
                "timestamp",
                "time",
                "timeStamp",
                "utc",
            )
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


def _resolve_samples_node(exercise: Mapping[str, Any]) -> Any:
    for key in (
        "samples",
        "sample",
        "sample-data",
        "sampleData",
        "data",
        "detailed-samples",
        "detailedSamples",
    ):
        if key in exercise and exercise[key] not in (None, ""):
            return exercise[key]

    # Some payloads expose sample groups directly on the exercise object.
    return exercise


def _extract_heart_rate_samples(samples_node: Any) -> list[Mapping[str, Any]]:
    return _extract_sample_series(
        samples_node=samples_node,
        series_keys=(
            "heart-rate",
            "heartRate",
            "heart_rate",
            "heartRateSamples",
            "heart-rate-samples",
            "hr",
        ),
        channel_aliases=("heart-rate", "heartRate", "heart_rate", "hr", "heartrate"),
        row_predicate=_looks_like_heart_rate_sample,
    )


def _extract_route_samples(samples_node: Any) -> list[Mapping[str, Any]]:
    return _extract_sample_series(
        samples_node=samples_node,
        series_keys=(
            "recorded-route",
            "recordedRoute",
            "route",
            "gps",
            "location",
            "position",
        ),
        channel_aliases=(
            "recorded-route",
            "recordedRoute",
            "route",
            "gps",
            "location",
            "position",
        ),
        row_predicate=_looks_like_route_sample,
    )


def _extract_sample_series(
    samples_node: Any,
    series_keys: tuple[str, ...],
    channel_aliases: tuple[str, ...],
    row_predicate: Callable[[Mapping[str, Any]], bool],
) -> list[Mapping[str, Any]]:
    series_key_aliases = {_normalize_label(key) for key in series_keys}
    normalized_channel_aliases = {_normalize_label(alias) for alias in channel_aliases}
    container_aliases = {
        "samples",
        "sample",
        "values",
        "data",
        "records",
        "items",
        "entries",
        "points",
        "channels",
        "measurements",
    }

    return _extract_sample_series_recursive(
        node=samples_node,
        series_key_aliases=series_key_aliases,
        channel_aliases=normalized_channel_aliases,
        container_aliases=container_aliases,
        row_predicate=row_predicate,
        depth=0,
    )


def _extract_sample_series_recursive(
    node: Any,
    series_key_aliases: set[str],
    channel_aliases: set[str],
    container_aliases: set[str],
    row_predicate: Callable[[Mapping[str, Any]], bool],
    depth: int,
) -> list[Mapping[str, Any]]:
    if depth > 6:
        return []

    if isinstance(node, list):
        dict_items = [item for item in node if isinstance(item, Mapping)]
        rows = [item for item in dict_items if row_predicate(item)]
        if rows:
            return rows

        typed_rows: list[Mapping[str, Any]] = []
        for item in dict_items:
            sample_type = _first_non_empty(
                item,
                "type",
                "sample-type",
                "sampleType",
                "name",
                "metric",
                "channel",
            )
            if _normalize_label(sample_type) not in channel_aliases:
                continue

            nested = _extract_sample_series_recursive(
                node=item,
                series_key_aliases=series_key_aliases,
                channel_aliases=channel_aliases,
                container_aliases=container_aliases,
                row_predicate=row_predicate,
                depth=depth + 1,
            )
            if nested:
                typed_rows.extend(nested)

        if typed_rows:
            return typed_rows

        for item in dict_items:
            nested = _extract_sample_series_recursive(
                node=item,
                series_key_aliases=series_key_aliases,
                channel_aliases=channel_aliases,
                container_aliases=container_aliases,
                row_predicate=row_predicate,
                depth=depth + 1,
            )
            if nested:
                return nested

        return []

    if not isinstance(node, Mapping):
        return []

    if row_predicate(node):
        return [node]

    for key, value in node.items():
        key_alias = _normalize_label(key)
        if (
            key_alias in series_key_aliases
            or key_alias in channel_aliases
            or key_alias in container_aliases
        ):
            nested = _extract_sample_series_recursive(
                node=value,
                series_key_aliases=series_key_aliases,
                channel_aliases=channel_aliases,
                container_aliases=container_aliases,
                row_predicate=row_predicate,
                depth=depth + 1,
            )
            if nested:
                return nested

    return []


def _looks_like_heart_rate_sample(sample: Mapping[str, Any]) -> bool:
    candidate_value = _first_non_empty(
        sample,
        "value",
        "heartRate",
        "heart_rate",
        "hr",
        "bpm",
        "beats-per-minute",
        "beatsPerMinute",
        "heart-rate",
    )
    return _to_int(candidate_value) is not None


def _looks_like_route_sample(sample: Mapping[str, Any]) -> bool:
    direct_coordinate = _first_non_empty(
        sample,
        "latitude",
        "lat",
        "latitudeDeg",
        "latitude_deg",
        "longitude",
        "lon",
        "lng",
        "longitudeDeg",
        "longitude_deg",
        "altitude",
        "elevation",
        "alt",
        "ele",
        "elevation_m",
        "elevationMeters",
        "coordinates",
    )
    if direct_coordinate is not None:
        return True

    nested_position = _first_non_empty(sample, "position", "location", "coordinate")
    if isinstance(nested_position, Mapping):
        nested_coordinate = _first_non_empty(
            nested_position,
            "latitude",
            "lat",
            "latitudeDeg",
            "latitude_deg",
            "longitude",
            "lon",
            "lng",
            "longitudeDeg",
            "longitude_deg",
            "altitude",
            "elevation",
            "alt",
            "ele",
            "elevation_m",
            "elevationMeters",
            "coordinates",
        )
        return nested_coordinate is not None

    return False


def _extract_route_coordinates(
    route_sample: Mapping[str, Any] | None,
) -> tuple[float | None, float | None, float | None]:
    if route_sample is None:
        return None, None, None

    latitude = _to_float(
        _first_non_empty(route_sample, "latitude", "lat", "latitudeDeg", "latitude_deg")
    )
    longitude = _to_float(
        _first_non_empty(route_sample, "longitude", "lon", "lng", "longitudeDeg", "longitude_deg")
    )
    elevation = _to_float(
        _first_non_empty(
            route_sample,
            "altitude",
            "elevation",
            "alt",
            "ele",
            "elevation_m",
            "elevationMeters",
        )
    )

    position = _first_non_empty(route_sample, "position", "location", "coordinate")
    if isinstance(position, Mapping):
        if latitude is None:
            latitude = _to_float(_first_non_empty(position, "latitude", "lat"))
        if longitude is None:
            longitude = _to_float(_first_non_empty(position, "longitude", "lon", "lng"))
        if elevation is None:
            elevation = _to_float(_first_non_empty(position, "altitude", "elevation", "alt", "ele"))

    coordinates = _first_non_empty(route_sample, "coordinates")
    if isinstance(coordinates, (list, tuple)):
        if longitude is None and len(coordinates) >= 1:
            longitude = _to_float(coordinates[0])
        if latitude is None and len(coordinates) >= 2:
            latitude = _to_float(coordinates[1])
        if elevation is None and len(coordinates) >= 3:
            elevation = _to_float(coordinates[2])

    return latitude, longitude, elevation


def _normalize_label(value: Any) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


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
