"""Data retrieval layer for Polar API integration."""

from datetime import datetime, timezone

from .config import OAuthConfig
from .errors import ApiError
from .models import FetchRequest, TelemetryRecord


def fetch_records(
    request: FetchRequest,
    oauth_config: OAuthConfig | None,
) -> list[TelemetryRecord]:
    """Fetch records for a request.

    The live API integration is intentionally not implemented yet.
    `--dry-run` returns a deterministic sample record so CLI/output paths can be validated.
    """

    _ = oauth_config

    if request.dry_run:
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

    raise ApiError(
        "Polar AccessLink integration is not implemented yet. "
        "Run with --dry-run to validate CLI flow and output schema."
    )
