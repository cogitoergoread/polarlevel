"""Fetcher integration-style tests with mocked HTTP session."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from polarlevel.config import OAuthConfig
from polarlevel.errors import ApiError
from polarlevel.fetcher import fetch_records
from polarlevel.models import FetchRequest


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

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        payload = kwargs.get("data")
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "timeout": timeout,
                "data": payload,
            }
        )
        if not self._responses:
            raise AssertionError("No fake response configured for request")
        return self._responses.pop(0)


@pytest.fixture
def oauth_config(tmp_path: Path) -> OAuthConfig:
    token_store_path = tmp_path / "oauth-tokens.json"
    return OAuthConfig(
        user_id="123",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8000/callback",
        access_token="access-token",
        refresh_token="refresh-token",
        accesslink_base_url="https://polar.example.test",
        token_endpoint_url="https://polar.example.test/oauth/token",
        token_store_path=token_store_path,
        http_timeout_seconds=10,
        retry_count=0,
    )


@pytest.fixture
def latest_request() -> FetchRequest:
    return FetchRequest(
        latest=True,
        start_date=None,
        end_date=None,
        output_path=Path("out.json"),
        output_format="json",
        dry_run=False,
    )


def test_fetch_records_runs_transaction_flow(
    oauth_config: OAuthConfig,
    latest_request: FetchRequest,
) -> None:
    session = FakeSession(
        responses=[
            FakeResponse(201, {"transaction-id": "tx1"}),
            FakeResponse(200, [{"id": "exercise-1"}]),
            FakeResponse(
                200,
                {
                    "id": "exercise-1",
                    "samples": {
                        "heart-rate": [
                            {"date-time": "2026-03-07T10:00:00Z", "value": 101},
                            {"date-time": "2026-03-07T10:00:05Z", "value": 102},
                        ],
                        "recorded-route": [
                            {
                                "date-time": "2026-03-07T10:00:00Z",
                                "latitude": 47.0,
                                "longitude": 19.0,
                                "altitude": 100.0,
                            },
                            {
                                "date-time": "2026-03-07T10:00:05Z",
                                "latitude": 47.1,
                                "longitude": 19.1,
                                "altitude": 101.0,
                            },
                        ],
                    },
                },
            ),
            FakeResponse(204, None),
        ]
    )

    records = fetch_records(latest_request, oauth_config, session=session)

    assert len(records) == 2
    assert records[0].user_id == "123"
    assert records[0].session_id == "exercise-1"
    assert records[0].heart_rate_bpm == 101
    assert records[0].latitude == pytest.approx(47.0)
    assert records[0].elevation_m == pytest.approx(100.0)
    assert records[1].timestamp_utc == "2026-03-07T10:00:05Z"

    methods = [call["method"] for call in session.calls]
    assert methods == ["POST", "GET", "GET", "PUT"]


def test_fetch_records_applies_date_range_filter(oauth_config: OAuthConfig) -> None:
    request = FetchRequest(
        latest=False,
        start_date=date(2026, 3, 8),
        end_date=date(2026, 3, 8),
        output_path=Path("out.csv"),
        output_format="csv",
        dry_run=False,
    )
    session = FakeSession(
        responses=[
            FakeResponse(201, {"transaction-id": "tx2"}),
            FakeResponse(200, [{"id": "exercise-2"}]),
            FakeResponse(
                200,
                {
                    "id": "exercise-2",
                    "samples": {
                        "heart-rate": [
                            {"date-time": "2026-03-07T23:59:59Z", "value": 99},
                            {"date-time": "2026-03-08T00:00:00Z", "value": 100},
                        ]
                    },
                },
            ),
            FakeResponse(200, {}),
        ]
    )

    records = fetch_records(request, oauth_config, session=session)

    assert len(records) == 1
    assert records[0].timestamp_utc == "2026-03-08T00:00:00Z"


def test_fetch_records_rejects_invalid_transaction_payload(
    oauth_config: OAuthConfig,
    latest_request: FetchRequest,
) -> None:
    session = FakeSession(
        responses=[
            FakeResponse(201, {"no-transaction-id": "missing"}),
        ]
    )

    with pytest.raises(ApiError, match="transaction id"):
        fetch_records(latest_request, oauth_config, session=session)


def test_fetch_records_refreshes_token_on_unauthorized(
    oauth_config: OAuthConfig,
    latest_request: FetchRequest,
) -> None:
    session = FakeSession(
        responses=[
            FakeResponse(401, {"error": "invalid_token"}),
            FakeResponse(200, {"access_token": "new-access", "refresh_token": "new-refresh"}),
            FakeResponse(201, {"transaction-id": "tx-refresh"}),
            FakeResponse(200, []),
            FakeResponse(204, None),
        ]
    )

    records = fetch_records(latest_request, oauth_config, session=session)

    assert records == []
    assert session.calls[0]["headers"]["Authorization"] == "Bearer access-token"
    assert session.calls[2]["headers"]["Authorization"] == "Bearer new-access"
    assert session.calls[1]["url"] == oauth_config.token_endpoint_url
    assert session.calls[1]["data"]["grant_type"] == "refresh_token"

    persisted = json.loads(oauth_config.token_store_path.read_text(encoding="utf-8"))
    assert persisted["access_token"] == "new-access"
    assert persisted["refresh_token"] == "new-refresh"


def test_fetch_records_refreshes_expiring_token_before_first_api_call(
    oauth_config: OAuthConfig,
    latest_request: FetchRequest,
) -> None:
    oauth_config.token_store_path.write_text(
        json.dumps(
            {
                "access_token": "stale-access",
                "refresh_token": "stale-refresh",
                "access_token_expires_at_utc": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    session = FakeSession(
        responses=[
            FakeResponse(
                200,
                {
                    "access_token": "fresh-access",
                    "refresh_token": "fresh-refresh",
                    "expires_in": 3600,
                },
            ),
            FakeResponse(201, {"transaction-id": "tx-preflight"}),
            FakeResponse(200, []),
            FakeResponse(204, None),
        ]
    )

    records = fetch_records(latest_request, oauth_config, session=session)

    assert records == []
    assert session.calls[0]["url"] == oauth_config.token_endpoint_url
    assert session.calls[0]["data"]["grant_type"] == "refresh_token"
    assert session.calls[0]["data"]["refresh_token"] == "stale-refresh"
    assert session.calls[1]["headers"]["Authorization"] == "Bearer fresh-access"

    persisted = json.loads(oauth_config.token_store_path.read_text(encoding="utf-8"))
    assert persisted["access_token"] == "fresh-access"
    assert persisted["refresh_token"] == "fresh-refresh"
    assert "access_token_expires_at_utc" in persisted


def test_fetch_records_extracts_samples_from_typed_channels(
    oauth_config: OAuthConfig,
    latest_request: FetchRequest,
) -> None:
    session = FakeSession(
        responses=[
            FakeResponse(201, {"transaction-id": "tx-typed"}),
            FakeResponse(200, [{"id": "exercise-typed"}]),
            FakeResponse(
                200,
                {
                    "id": "exercise-typed",
                    "samples": {
                        "sample": [
                            {
                                "type": "HEART_RATE",
                                "values": [
                                    {"timeStamp": "2026-03-07T10:00:00Z", "bpm": "111"},
                                    {
                                        "timeStamp": "2026-03-07T10:00:05Z",
                                        "beatsPerMinute": 112,
                                    },
                                ],
                            },
                            {
                                "type": "recordedRoute",
                                "data": [
                                    {
                                        "timeStamp": "2026-03-07T10:00:00Z",
                                        "position": {"lat": 47.2, "lon": 19.2, "alt": 150},
                                    },
                                    {
                                        "timeStamp": "2026-03-07T10:00:05Z",
                                        "coordinates": [19.3, 47.3, 151],
                                    },
                                ],
                            },
                        ]
                    },
                },
            ),
            FakeResponse(204, None),
        ]
    )

    records = fetch_records(latest_request, oauth_config, session=session)

    assert len(records) == 2
    assert records[0].heart_rate_bpm == 111
    assert records[0].latitude == pytest.approx(47.2)
    assert records[0].longitude == pytest.approx(19.2)
    assert records[0].elevation_m == pytest.approx(150.0)

    assert records[1].heart_rate_bpm == 112
    assert records[1].latitude == pytest.approx(47.3)
    assert records[1].longitude == pytest.approx(19.3)
    assert records[1].elevation_m == pytest.approx(151.0)


def test_fetch_records_extracts_sample_data_variants(
    oauth_config: OAuthConfig,
    latest_request: FetchRequest,
) -> None:
    session = FakeSession(
        responses=[
            FakeResponse(201, {"transaction-id": "tx-sample-data"}),
            FakeResponse(200, [{"id": "exercise-sample-data"}]),
            FakeResponse(
                200,
                {
                    "id": "exercise-sample-data",
                    "sampleData": {
                        "heartRateSamples": {
                            "items": [
                                {
                                    "utc": "2026-03-07T11:00:00Z",
                                    "beats-per-minute": "121",
                                }
                            ]
                        },
                        "gps": {
                            "points": [
                                {
                                    "utc": "2026-03-07T11:00:00Z",
                                    "latitudeDeg": "47.4",
                                    "longitudeDeg": "19.4",
                                    "elevation_m": "88.5",
                                }
                            ]
                        },
                    },
                },
            ),
            FakeResponse(200, {}),
        ]
    )

    records = fetch_records(latest_request, oauth_config, session=session)

    assert len(records) == 1
    assert records[0].timestamp_utc == "2026-03-07T11:00:00Z"
    assert records[0].heart_rate_bpm == 121
    assert records[0].latitude == pytest.approx(47.4)
    assert records[0].longitude == pytest.approx(19.4)
    assert records[0].elevation_m == pytest.approx(88.5)
