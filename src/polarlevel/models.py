"""Shared data models for CLI and data processing."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FetchRequest:
    """Normalized fetch request from CLI arguments."""

    latest: bool
    start_date: date | None
    end_date: date | None
    output_path: Path
    output_format: str
    dry_run: bool


@dataclass(frozen=True)
class TelemetryRecord:
    """Normalized output record contract."""

    user_id: str
    session_id: str
    timestamp_utc: str
    heart_rate_bpm: int
    latitude: float | None
    longitude: float | None
    elevation_m: float | None
    source: str = "polar-accesslink"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "timestamp_utc": self.timestamp_utc,
            "heart_rate_bpm": self.heart_rate_bpm,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "source": self.source,
        }
